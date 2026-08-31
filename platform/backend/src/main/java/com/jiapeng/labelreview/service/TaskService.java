package com.jiapeng.labelreview.service;

import com.jiapeng.labelreview.api.ApiDtos.DecisionRequest;
import com.jiapeng.labelreview.api.ApiDtos.ImageCandidateView;
import com.jiapeng.labelreview.api.ApiDtos.RecentDecisionView;
import com.jiapeng.labelreview.api.ApiDtos.TaskView;
import com.jiapeng.labelreview.config.ReviewProperties;
import com.jiapeng.labelreview.domain.AppUser;
import com.jiapeng.labelreview.domain.DecisionType;
import com.jiapeng.labelreview.domain.ReviewDecision;
import com.jiapeng.labelreview.domain.ReviewTask;
import com.jiapeng.labelreview.domain.TaskState;
import com.jiapeng.labelreview.repository.DecisionRepository;
import com.jiapeng.labelreview.repository.TaskRepository;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Function;
import java.util.stream.Collectors;

@Service
public class TaskService {

    private final TaskRepository tasks;
    private final DecisionRepository decisions;
    private final ProjectService projects;
    private final AuditService audit;
    private final ReviewProperties properties;

    public TaskService(
            TaskRepository tasks,
            DecisionRepository decisions,
            ProjectService projects,
            AuditService audit,
            ReviewProperties properties) {
        this.tasks = tasks;
        this.decisions = decisions;
        this.projects = projects;
        this.audit = audit;
        this.properties = properties;
    }

    @Transactional
    public Optional<TaskView> claimNext(Long projectId, AppUser reviewer) {
        projects.requireAccess(projectId, reviewer);
        Instant now = Instant.now();
        Optional<ReviewTask> current = tasks.findFirstByClaimedByUsernameAndStateOrderByUpdatedAtDesc(
                reviewer.getUsername(),
                TaskState.CLAIMED);
        if (current.isPresent() && current.get().getLeaseUntil() != null && current.get().getLeaseUntil().isAfter(now)) {
            if (!current.get().getProject().getId().equals(projectId)) {
                throw new ResponseStatusException(
                        HttpStatus.CONFLICT,
                        "Release the active task in project " + current.get().getProject().getId() + " before switching projects");
            }
            return current.map(TaskService::view);
        }
        // Search a small window because an older deployment may have left pending
        // siblings beside a live claim from another reviewer. New claims lease all
        // candidates from one image together, so reviewers keep the full context.
        List<ReviewTask> candidates = tasks.findClaimable(projectId, now, PageRequest.of(0, 100));
        for (ReviewTask candidate : candidates) {
            Optional<ReviewTask> claimed = claimImage(candidate, reviewer, now);
            if (claimed.isPresent()) {
                ReviewTask task = claimed.get();
                audit.record(
                        reviewer.getUsername(),
                        "IMAGE_CLAIMED",
                        "PROJECT",
                        projectId,
                        "task=" + task.getId() + ",candidate=" + task.getCandidateId()
                                + ",image=" + task.getImageName());
                return Optional.of(view(task));
            }
        }
        return Optional.empty();
    }

    @Transactional
    public TaskView claim(Long taskId, AppUser reviewer) {
        Instant now = Instant.now();
        Optional<ReviewTask> current = tasks.findFirstByClaimedByUsernameAndStateOrderByUpdatedAtDesc(
                reviewer.getUsername(),
                TaskState.CLAIMED);
        ReviewTask task = tasks.findByIdForUpdate(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Task not found"));
        projects.requireAccess(task.getProject().getId(), reviewer);
        if (current.isPresent() && current.get().getLeaseUntil() != null && current.get().getLeaseUntil().isAfter(now)) {
            ReviewTask active = current.get();
            boolean sameImage = active.getProject().getId().equals(task.getProject().getId())
                    && active.getSplit().equals(task.getSplit())
                    && active.getImageName().equals(task.getImageName());
            if (!sameImage) {
                throw new ResponseStatusException(
                        HttpStatus.CONFLICT,
                        "Release the active image before claiming another candidate");
            }
        }

        if (task.getState() == TaskState.CLAIMED
                && task.getClaimedBy() != null
                && task.getClaimedBy().getId().equals(reviewer.getId())
                && task.getLeaseUntil() != null
                && task.getLeaseUntil().isAfter(now)) {
            return view(task);
        }
        boolean expiredClaim = task.getState() == TaskState.CLAIMED
                && task.getLeaseUntil() != null
                && !task.getLeaseUntil().isAfter(now);
        if (task.getState() != TaskState.PENDING && !expiredClaim) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Candidate is no longer available");
        }
        ReviewTask claimed = claimImage(task, reviewer, now)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.CONFLICT, "Image is being reviewed by another reviewer"));
        audit.record(
                reviewer.getUsername(),
                "IMAGE_CLAIMED_FROM_CANDIDATE",
                "PROJECT",
                task.getProject().getId(),
                "task=" + task.getId() + ",candidate=" + task.getCandidateId()
                        + ",image=" + task.getImageName());
        return view(claimed);
    }

    @Transactional(readOnly = true)
    public List<ImageCandidateView> imageCandidates(Long taskId, AppUser actor) {
        ReviewTask anchor = tasks.findById(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Task not found"));
        projects.requireAccess(anchor.getProject().getId(), actor);
        List<ReviewTask> siblings = tasks.findByProjectIdAndSplitAndImageNameOrderById(
                anchor.getProject().getId(),
                anchor.getSplit(),
                anchor.getImageName());
        Map<Long, ReviewDecision> decisionByTask = decisions.findByTaskIdIn(
                        siblings.stream().map(ReviewTask::getId).toList())
                .stream()
                .collect(Collectors.toMap(decision -> decision.getTask().getId(), Function.identity()));
        return siblings.stream()
                .map(task -> imageCandidateView(task, decisionByTask.get(task.getId())))
                .toList();
    }

    @Transactional(readOnly = true)
    public TaskView task(Long taskId, AppUser actor) {
        ReviewTask task = tasks.findById(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Task not found"));
        projects.requireAccess(task.getProject().getId(), actor);
        return view(task);
    }

    @Transactional(readOnly = true)
    public List<RecentDecisionView> recentDecisions(Long projectId, int limit, AppUser actor) {
        projects.requireAccess(projectId, actor);
        int safeLimit = Math.max(1, Math.min(limit, 50));
        return decisions.findRecentByReviewerAndProject(actor.getId(), projectId, PageRequest.of(0, safeLimit))
                .stream()
                .map(TaskService::recentDecisionView)
                .toList();
    }

    @Transactional
    public TaskView heartbeat(Long taskId, AppUser reviewer) {
        ReviewTask task = requireOwnedTask(taskId, reviewer, true);
        Instant deadline = leaseDeadline(Instant.now());
        List<ReviewTask> siblings = imageTasksForUpdate(task);
        siblings.stream()
                .filter(sibling -> isClaimedBy(sibling, reviewer))
                .forEach(sibling -> sibling.extendLease(deadline));
        tasks.flush();
        return view(task);
    }

    @Transactional
    public void release(Long taskId, AppUser reviewer) {
        ReviewTask task = requireOwnedTask(taskId, reviewer, false);
        List<ReviewTask> siblings = imageTasksForUpdate(task);
        long released = siblings.stream()
                .filter(sibling -> isClaimedBy(sibling, reviewer))
                .peek(ReviewTask::release)
                .count();
        audit.record(
                reviewer.getUsername(),
                "IMAGE_RELEASED",
                "PROJECT",
                task.getProject().getId(),
                "task=" + task.getId() + ",image=" + task.getImageName() + ",released=" + released);
    }

    @Transactional
    public TaskView decide(Long taskId, DecisionRequest request, AppUser reviewer) {
        ReviewTask task = requireOwnedTask(taskId, reviewer, true);
        if (!request.expectedVersion().equals(task.getVersion())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Task changed; refresh before deciding");
        }
        if (!DecisionPolicy.isAllowed(task.getRecommendedAction(), request.decision())) {
            throw new ResponseStatusException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "Decision " + request.decision() + " is not allowed for " + task.getRecommendedAction());
        }
        if (decisions.existsByTaskId(taskId)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Task already has a decision");
        }
        String comment = request.comment() == null ? "" : request.comment().trim();
        decisions.save(new ReviewDecision(task, reviewer, request.decision(), comment));
        task.complete(request.decision() == DecisionType.UNCERTAIN);
        tasks.flush();
        audit.record(
                reviewer.getUsername(),
                "TASK_DECIDED",
                "PROJECT",
                task.getProject().getId(),
                "task=" + task.getId() + ",decision=" + request.decision());
        return view(task);
    }

    @Transactional
    public TaskView reviseDecision(Long taskId, DecisionRequest request, AppUser actor) {
        ReviewTask task = tasks.findByIdForUpdate(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Task not found"));
        projects.requireAccess(task.getProject().getId(), actor);
        if (!request.expectedVersion().equals(task.getVersion())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Task changed; refresh before revising");
        }
        if (task.getState() != TaskState.COMPLETED && task.getState() != TaskState.ESCALATED) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Only a completed decision can be revised");
        }
        ReviewDecision decision = decisions.findByTaskId(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Decision not found"));
        boolean ownsDecision = decision.getReviewer().getId().equals(actor.getId());
        if (!ownsDecision && actor.getRole() != com.jiapeng.labelreview.domain.UserRole.ADMIN) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Only the original reviewer or an administrator can revise this decision");
        }
        if (!DecisionPolicy.isAllowed(task.getRecommendedAction(), request.decision())) {
            throw new ResponseStatusException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "Decision " + request.decision() + " is not allowed for " + task.getRecommendedAction());
        }
        DecisionType previous = decision.getDecision();
        String comment = request.comment() == null ? "" : request.comment().trim();
        decision.revise(request.decision(), comment);
        task.complete(request.decision() == DecisionType.UNCERTAIN);
        tasks.flush();
        audit.record(
                actor.getUsername(),
                "TASK_DECISION_REVISED",
                "PROJECT",
                task.getProject().getId(),
                "task=" + task.getId() + ",from=" + previous + ",to=" + request.decision());
        return view(task);
    }

    @Transactional(readOnly = true)
    public Resource visual(Long taskId, AppUser actor) {
        ReviewTask task = tasks.findById(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Task not found"));
        projects.requireAccess(task.getProject().getId(), actor);
        Path root = Path.of(task.getProject().getReviewRoot()).toAbsolutePath().normalize();
        Path visual = root.resolve(task.getVisualFile()).normalize();
        if (!visual.startsWith(root)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Visual path escapes project root");
        }
        if (!Files.isRegularFile(visual)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Visual file not found");
        }
        return new FileSystemResource(visual);
    }

    private ReviewTask requireOwnedTask(Long taskId, AppUser reviewer, boolean requireLiveLease) {
        ReviewTask task = tasks.findByIdForUpdate(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Task not found"));
        if (task.getState() != TaskState.CLAIMED
                || task.getClaimedBy() == null
                || !task.getClaimedBy().getId().equals(reviewer.getId())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Task is not claimed by the current reviewer");
        }
        if (requireLiveLease && (task.getLeaseUntil() == null || !task.getLeaseUntil().isAfter(Instant.now()))) {
            task.release();
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Task lease expired; claim a task again");
        }
        return task;
    }

    private Instant leaseDeadline(Instant now) {
        return now.plus(properties.leaseMinutes(), ChronoUnit.MINUTES);
    }

    private Optional<ReviewTask> claimImage(ReviewTask anchor, AppUser reviewer, Instant now) {
        List<ReviewTask> siblings = imageTasksForUpdate(anchor);
        boolean claimedByOther = siblings.stream().anyMatch(sibling ->
                sibling.getState() == TaskState.CLAIMED
                        && sibling.getClaimedBy() != null
                        && !sibling.getClaimedBy().getId().equals(reviewer.getId())
                        && sibling.getLeaseUntil() != null
                        && sibling.getLeaseUntil().isAfter(now));
        if (claimedByOther) {
            return Optional.empty();
        }

        Instant deadline = leaseDeadline(now);
        for (ReviewTask sibling : siblings) {
            boolean expired = sibling.getState() == TaskState.CLAIMED
                    && (sibling.getLeaseUntil() == null || !sibling.getLeaseUntil().isAfter(now));
            if (sibling.getState() == TaskState.PENDING || expired || isClaimedBy(sibling, reviewer)) {
                sibling.claim(reviewer, deadline);
            }
        }
        tasks.flush();
        return siblings.stream().filter(sibling -> sibling.getId().equals(anchor.getId())).findFirst();
    }

    private List<ReviewTask> imageTasksForUpdate(ReviewTask task) {
        return tasks.findImageTasksForUpdate(
                task.getProject().getId(),
                task.getSplit(),
                task.getImageName());
    }

    private static boolean isClaimedBy(ReviewTask task, AppUser reviewer) {
        return task.getState() == TaskState.CLAIMED
                && task.getClaimedBy() != null
                && task.getClaimedBy().getId().equals(reviewer.getId());
    }

    private static TaskView view(ReviewTask task) {
        return new TaskView(
                task.getId(),
                task.getVersion(),
                task.getProject().getId(),
                task.getCandidateId(),
                task.getSplit(),
                task.getImageName(),
                task.getClassName(),
                task.getConfidence(),
                task.getCaseCode(),
                task.getRecommendedAction(),
                task.getState(),
                task.getClaimedBy() == null ? null : task.getClaimedBy().getUsername(),
                task.getLeaseUntil(),
                "/api/tasks/" + task.getId() + "/visual");
    }

    private static ImageCandidateView imageCandidateView(ReviewTask task, ReviewDecision decision) {
        return new ImageCandidateView(
                task.getId(),
                task.getVersion(),
                task.getCandidateId(),
                task.getClassName(),
                task.getConfidence(),
                task.getCaseCode(),
                task.getRecommendedAction(),
                task.getState(),
                task.getClaimedBy() == null ? null : task.getClaimedBy().getUsername(),
                decision == null ? null : decision.getDecision(),
                decision == null ? null : decision.getReviewer().getUsername(),
                decision == null ? null : decision.getComment());
    }

    private static RecentDecisionView recentDecisionView(ReviewDecision decision) {
        ReviewTask task = decision.getTask();
        return new RecentDecisionView(
                task.getId(),
                task.getVersion(),
                task.getProject().getId(),
                task.getCandidateId(),
                task.getSplit(),
                task.getImageName(),
                task.getClassName(),
                task.getConfidence(),
                task.getCaseCode(),
                task.getRecommendedAction(),
                task.getState(),
                decision.getDecision(),
                decision.getComment(),
                decision.getDecidedAt());
    }
}
