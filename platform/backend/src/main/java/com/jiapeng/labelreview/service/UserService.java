package com.jiapeng.labelreview.service;

import com.jiapeng.labelreview.api.ApiDtos.CreateUserRequest;
import com.jiapeng.labelreview.api.ApiDtos.UserView;
import com.jiapeng.labelreview.domain.AppUser;
import com.jiapeng.labelreview.domain.ProjectMember;
import com.jiapeng.labelreview.domain.ProjectStatus;
import com.jiapeng.labelreview.domain.ReviewProject;
import com.jiapeng.labelreview.domain.UserRole;
import com.jiapeng.labelreview.repository.ProjectMemberRepository;
import com.jiapeng.labelreview.repository.ProjectRepository;
import com.jiapeng.labelreview.repository.UserRepository;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

@Service
public class UserService {

    private final UserRepository users;
    private final ProjectRepository projects;
    private final ProjectMemberRepository memberships;
    private final PasswordEncoder encoder;
    private final AuditService audit;

    public UserService(
            UserRepository users,
            ProjectRepository projects,
            ProjectMemberRepository memberships,
            PasswordEncoder encoder,
            AuditService audit) {
        this.users = users;
        this.projects = projects;
        this.memberships = memberships;
        this.encoder = encoder;
        this.audit = audit;
    }

    @Transactional
    public UserView create(CreateUserRequest request, AppUser actor) {
        String username = request.username().trim().toLowerCase(Locale.ROOT);
        if (users.existsByUsername(username)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Username already exists");
        }

        List<Long> requestedProjectIds = request.projectIds() == null
                ? List.of()
                : request.projectIds().stream().distinct().toList();
        if (request.role() != UserRole.ADMIN && requestedProjectIds.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Reviewer or auditor must be assigned to a project");
        }

        Map<Long, ReviewProject> projectById = projects.findAllById(requestedProjectIds).stream()
                .collect(Collectors.toMap(ReviewProject::getId, Function.identity()));
        if (projectById.size() != requestedProjectIds.size()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "One or more selected projects do not exist");
        }
        List<ReviewProject> assignedProjects = requestedProjectIds.stream()
                .map(projectById::get)
                .toList();
        if (assignedProjects.stream().anyMatch(project -> project.getStatus() != ProjectStatus.OPEN)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Archived projects cannot receive new members");
        }

        AppUser user = users.save(new AppUser(
                username,
                encoder.encode(request.password()),
                request.displayName().trim(),
                request.role()));
        if (request.role() != UserRole.ADMIN) {
            memberships.saveAll(assignedProjects.stream()
                    .map(project -> new ProjectMember(project, user, actor))
                    .toList());
        }
        String projectDetails = request.role() == UserRole.ADMIN
                ? "all(admin)"
                : requestedProjectIds.toString();
        audit.record(
                actor.getUsername(),
                "USER_CREATED",
                "USER",
                user.getId(),
                "role=" + user.getRole() + ",projects=" + projectDetails);
        return view(user);
    }

    @Transactional(readOnly = true)
    public List<UserView> list() {
        return users.findAll().stream().map(UserService::view).toList();
    }

    public static UserView view(AppUser user) {
        return new UserView(
                user.getId(),
                user.getUsername(),
                user.getDisplayName(),
                user.getRole(),
                user.isEnabled());
    }
}
