package com.jiapeng.labelreview.api;

import com.jiapeng.labelreview.api.ApiDtos.DecisionRequest;
import com.jiapeng.labelreview.api.ApiDtos.TaskView;
import com.jiapeng.labelreview.domain.AppUser;
import com.jiapeng.labelreview.service.CurrentUserService;
import com.jiapeng.labelreview.service.TaskService;
import jakarta.validation.Valid;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.MediaTypeFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tasks")
public class TaskController {

    private final TaskService tasks;
    private final CurrentUserService currentUsers;

    public TaskController(TaskService tasks, CurrentUserService currentUsers) {
        this.tasks = tasks;
        this.currentUsers = currentUsers;
    }

    @PostMapping("/claim-next")
    @PreAuthorize("hasAnyRole('ADMIN','REVIEWER')")
    public ResponseEntity<TaskView> claimNext(@RequestParam Long projectId, Authentication authentication) {
        AppUser reviewer = currentUsers.require(authentication);
        return tasks.claimNext(projectId, reviewer)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.noContent().build());
    }

    @PostMapping("/{taskId}/heartbeat")
    @PreAuthorize("hasAnyRole('ADMIN','REVIEWER')")
    public TaskView heartbeat(@PathVariable Long taskId, Authentication authentication) {
        return tasks.heartbeat(taskId, currentUsers.require(authentication));
    }

    @PostMapping("/{taskId}/release")
    @PreAuthorize("hasAnyRole('ADMIN','REVIEWER')")
    public ResponseEntity<Void> release(@PathVariable Long taskId, Authentication authentication) {
        tasks.release(taskId, currentUsers.require(authentication));
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/{taskId}/decision")
    @PreAuthorize("hasAnyRole('ADMIN','REVIEWER')")
    public TaskView decide(
            @PathVariable Long taskId,
            @Valid @RequestBody DecisionRequest request,
            Authentication authentication) {
        return tasks.decide(taskId, request, currentUsers.require(authentication));
    }

    @GetMapping("/{taskId}/visual")
    public ResponseEntity<Resource> visual(@PathVariable Long taskId, Authentication authentication) {
        Resource resource = tasks.visual(taskId, currentUsers.require(authentication));
        MediaType mediaType = MediaTypeFactory.getMediaType(resource).orElse(MediaType.APPLICATION_OCTET_STREAM);
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, "private, max-age=300")
                .contentType(mediaType)
                .body(resource);
    }
}
