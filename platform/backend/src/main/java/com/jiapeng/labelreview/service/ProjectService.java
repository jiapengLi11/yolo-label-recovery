package com.jiapeng.labelreview.service;

import com.jiapeng.labelreview.api.ApiDtos.CreateProjectRequest;
import com.jiapeng.labelreview.api.ApiDtos.ImportResult;
import com.jiapeng.labelreview.api.ApiDtos.HistoricalDecisionImportRequest;
import com.jiapeng.labelreview.api.ApiDtos.HistoricalDecisionImportResult;
import com.jiapeng.labelreview.api.ApiDtos.ProgressView;
import com.jiapeng.labelreview.api.ApiDtos.ProjectMemberView;
import com.jiapeng.labelreview.api.ApiDtos.ProjectView;
import com.jiapeng.labelreview.api.ApiDtos.TaskImportRequest;
import com.jiapeng.labelreview.domain.AppUser;
import com.jiapeng.labelreview.domain.DecisionType;
import com.jiapeng.labelreview.domain.ProjectMember;
import com.jiapeng.labelreview.domain.ReviewDecision;
import com.jiapeng.labelreview.domain.ReviewProject;
import com.jiapeng.labelreview.domain.ReviewTask;
import com.jiapeng.labelreview.domain.TaskState;
import com.jiapeng.labelreview.domain.UserRole;
import com.jiapeng.labelreview.repository.DecisionRepository;
import com.jiapeng.labelreview.repository.ProjectMemberRepository;
import com.jiapeng.labelreview.repository.ProjectRepository;
import com.jiapeng.labelreview.repository.TaskRepository;
import com.jiapeng.labelreview.repository.UserRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

@Service
public class ProjectService {

    private static final int MAX_IMPORT_BATCH = 500;

    private final ProjectRepository projects;
    private final ProjectMemberRepository members;
    private final UserRepository users;
    private final TaskRepository tasks;
    private final DecisionRepository decisions;
    private final AuditService audit;

    public ProjectService(
            ProjectRepository projects,
            ProjectMemberRepository members,
            UserRepository users,
            TaskRepository tasks,
            DecisionRepository decisions,
            AuditService audit) {
        this.projects = projects;
        this.members = members;
        this.users = users;
        this.tasks = tasks;
        this.decisions = decisions;
        this.audit = audit;
    }

    @Transactional
    public ProjectView create(CreateProjectRequest request, AppUser actor) {
        Path root = Path.of(request.reviewRoot()).toAbsolutePath().normalize();
        ReviewProject project = projects.save(new ReviewProject(
                request.name().trim(),
                request.description() == null ? "" : request.description().trim(),
                root.toString(),
                actor));
        audit.record(actor.getUsername(), "PROJECT_CREATED", "PROJECT", project.getId(), "name=" + project.getName());
        return view(project);
    }

    @Transactional(readOnly = true)
    public List<ProjectView> list(AppUser actor) {
        if (actor.getRole() == UserRole.ADMIN) {
            return projects.findAll().stream().map(ProjectService::view).toList();
        }
        return members.findByUserIdOrderByAssignedAt(actor.getId()).stream()
                .map(ProjectMember::getProject)
                .map(ProjectService::view)
                .toList();
    }

    @Transactional
    public ProjectMemberView assignMember(Long projectId, String username, AppUser actor) {
        ReviewProject project = requireProject(projectId);
        AppUser user = users.findByUsername(username.trim().toLowerCase(Locale.ROOT))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "User not found"));
        if (!user.isEnabled()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Disabled user cannot be assigned");
        }
        if (members.existsByProjectIdAndUserId(projectId, user.getId())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "User is already assigned to this project");
        }
        ProjectMember membership = members.save(new ProjectMember(project, user, actor));
        audit.record(actor.getUsername(), "PROJECT_MEMBER_ASSIGNED", "PROJECT", projectId, "username=" + user.getUsername());
        return memberView(membership);
    }

    @Transactional(readOnly = true)
    public List<ProjectMemberView> listMembers(Long projectId) {
        requireProject(projectId);
        return members.findByProjectIdOrderByAssignedAt(projectId).stream()
                .map(ProjectService::memberView)
                .toList();
    }

    @Transactional
    public ImportResult importTasks(Long projectId, List<TaskImportRequest> rows, AppUser actor) {
        if (rows.isEmpty() || rows.size() > MAX_IMPORT_BATCH) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Each import batch must contain between 1 and " + MAX_IMPORT_BATCH + " tasks");
        }
        ReviewProject project = requireProject(projectId);
        Set<String> requestedIds = new HashSet<>();
        for (TaskImportRequest row : rows) {
            if (!requestedIds.add(row.candidateId())) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Duplicate candidate in import batch: " + row.candidateId());
            }
        }
        Set<String> existing = new HashSet<>(tasks.findExistingCandidateIds(projectId, requestedIds));
        List<ReviewTask> additions = rows.stream()
                .filter(row -> !existing.contains(row.candidateId()))
                .map(row -> new ReviewTask(
                        project,
                        row.candidateId(),
                        row.split(),
                        row.imageName(),
                        row.className(),
                        row.confidence(),
                        row.caseCode(),
                        row.recommendedAction(),
                        row.visualFile()))
                .toList();
        tasks.saveAll(additions);
        audit.record(
                actor.getUsername(),
                "TASKS_IMPORTED",
                "PROJECT",
                projectId,
                "received=" + rows.size() + ",created=" + additions.size());
        return new ImportResult(rows.size(), additions.size(), existing.size());
    }

    @Transactional
    public HistoricalDecisionImportResult importHistoricalDecisions(
            Long projectId,
            List<HistoricalDecisionImportRequest> rows,
            AppUser actor) {
        if (rows.isEmpty() || rows.size() > MAX_IMPORT_BATCH) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Each import batch must contain between 1 and " + MAX_IMPORT_BATCH + " decisions");
        }
        requireProject(projectId);
        Set<String> candidateIds = new HashSet<>();
        for (HistoricalDecisionImportRequest row : rows) {
            if (!candidateIds.add(row.candidateId())) {
                throw new ResponseStatusException(
                        HttpStatus.BAD_REQUEST,
                        "Duplicate candidate in decision import batch: " + row.candidateId());
            }
        }

        Map<String, ReviewTask> taskByCandidate = tasks.findByProjectIdAndCandidateIds(projectId, candidateIds).stream()
                .collect(Collectors.toMap(ReviewTask::getCandidateId, Function.identity()));
        Set<Long> existingTaskIds = new HashSet<>(
                decisions.findTaskIdsByProjectAndCandidateIds(projectId, candidateIds));
        List<ReviewDecision> additions = new ArrayList<>();
        int unknown = 0;
        int skipped = 0;
        int invalid = 0;

        for (HistoricalDecisionImportRequest row : rows) {
            ReviewTask task = taskByCandidate.get(row.candidateId());
            if (task == null) {
                unknown++;
                continue;
            }
            if (existingTaskIds.contains(task.getId())) {
                skipped++;
                continue;
            }
            if (!DecisionPolicy.isAllowed(task.getRecommendedAction(), row.decision())) {
                invalid++;
                continue;
            }
            String comment = row.comment() == null ? "" : row.comment().trim();
            additions.add(new ReviewDecision(task, actor, row.decision(), comment));
            task.complete(row.decision() == DecisionType.UNCERTAIN);
        }

        decisions.saveAll(additions);
        tasks.flush();
        audit.record(
                actor.getUsername(),
                "HISTORICAL_DECISIONS_IMPORTED",
                "PROJECT",
                projectId,
                "received=" + rows.size()
                        + ",imported=" + additions.size()
                        + ",skipped=" + skipped
                        + ",unknown=" + unknown
                        + ",invalid=" + invalid);
        return new HistoricalDecisionImportResult(rows.size(), additions.size(), skipped, unknown, invalid);
    }

    @Transactional(readOnly = true)
    public ProgressView progress(Long projectId, AppUser actor) {
        requireAccess(projectId, actor);
        long total = tasks.countByProjectId(projectId);
        long pending = tasks.countByProjectIdAndState(projectId, TaskState.PENDING);
        long claimed = tasks.countByProjectIdAndState(projectId, TaskState.CLAIMED);
        long completed = tasks.countByProjectIdAndState(projectId, TaskState.COMPLETED);
        long escalated = tasks.countByProjectIdAndState(projectId, TaskState.ESCALATED);
        double rate = total == 0 ? 0.0 : (double) (completed + escalated) / total;
        return new ProgressView(total, pending, claimed, completed, escalated, rate);
    }

    public ReviewProject requireProject(Long projectId) {
        return projects.findById(projectId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Project not found"));
    }

    public ReviewProject requireAccess(Long projectId, AppUser actor) {
        ReviewProject project = requireProject(projectId);
        if (actor.getRole() != UserRole.ADMIN && !members.existsByProjectIdAndUserId(projectId, actor.getId())) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "User is not assigned to this project");
        }
        return project;
    }

    private static ProjectView view(ReviewProject project) {
        return new ProjectView(
                project.getId(),
                project.getName(),
                project.getDescription(),
                project.getStatus(),
                project.getCreatedBy().getUsername(),
                project.getCreatedAt());
    }

    private static ProjectMemberView memberView(ProjectMember membership) {
        AppUser user = membership.getUser();
        return new ProjectMemberView(
                membership.getId(),
                user.getId(),
                user.getUsername(),
                user.getDisplayName(),
                user.getRole(),
                membership.getAssignedBy().getUsername(),
                membership.getAssignedAt());
    }
}
