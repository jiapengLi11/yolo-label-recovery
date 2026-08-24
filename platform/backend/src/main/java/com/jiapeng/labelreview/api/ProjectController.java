package com.jiapeng.labelreview.api;

import com.jiapeng.labelreview.api.ApiDtos.AuditView;
import com.jiapeng.labelreview.api.ApiDtos.CreateProjectRequest;
import com.jiapeng.labelreview.api.ApiDtos.ImportResult;
import com.jiapeng.labelreview.api.ApiDtos.ProgressView;
import com.jiapeng.labelreview.api.ApiDtos.ProjectMemberRequest;
import com.jiapeng.labelreview.api.ApiDtos.ProjectMemberView;
import com.jiapeng.labelreview.api.ApiDtos.ProjectView;
import com.jiapeng.labelreview.api.ApiDtos.TaskImportRequest;
import com.jiapeng.labelreview.domain.AppUser;
import com.jiapeng.labelreview.service.AuditService;
import com.jiapeng.labelreview.service.CurrentUserService;
import com.jiapeng.labelreview.service.ProjectService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Size;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/projects")
public class ProjectController {

    private final ProjectService projects;
    private final CurrentUserService currentUsers;
    private final AuditService audit;

    public ProjectController(ProjectService projects, CurrentUserService currentUsers, AuditService audit) {
        this.projects = projects;
        this.currentUsers = currentUsers;
        this.audit = audit;
    }

    @GetMapping
    public List<ProjectView> list(Authentication authentication) {
        return projects.list(currentUsers.require(authentication));
    }

    @PostMapping
    @PreAuthorize("hasRole('ADMIN')")
    public ProjectView create(@Valid @RequestBody CreateProjectRequest request, Authentication authentication) {
        return projects.create(request, currentUsers.require(authentication));
    }

    @PostMapping("/{projectId}/tasks:batch")
    @PreAuthorize("hasRole('ADMIN')")
    public ImportResult importTasks(
            @PathVariable Long projectId,
            @Size(min = 1, max = 500) @RequestBody List<@Valid TaskImportRequest> rows,
            Authentication authentication) {
        AppUser actor = currentUsers.require(authentication);
        return projects.importTasks(projectId, rows, actor);
    }

    @GetMapping("/{projectId}/progress")
    public ProgressView progress(@PathVariable Long projectId, Authentication authentication) {
        return projects.progress(projectId, currentUsers.require(authentication));
    }

    @GetMapping("/{projectId}/members")
    @PreAuthorize("hasRole('ADMIN')")
    public List<ProjectMemberView> members(@PathVariable Long projectId) {
        return projects.listMembers(projectId);
    }

    @PostMapping("/{projectId}/members")
    @PreAuthorize("hasRole('ADMIN')")
    public ProjectMemberView assignMember(
            @PathVariable Long projectId,
            @Valid @RequestBody ProjectMemberRequest request,
            Authentication authentication) {
        return projects.assignMember(projectId, request.username(), currentUsers.require(authentication));
    }

    @GetMapping("/{projectId}/audit")
    @PreAuthorize("hasAnyRole('ADMIN','AUDITOR')")
    public List<AuditView> audit(
            @PathVariable Long projectId,
            @RequestParam(defaultValue = "100") int limit,
            Authentication authentication) {
        projects.requireAccess(projectId, currentUsers.require(authentication));
        return audit.listProjectEvents(projectId, limit);
    }
}
