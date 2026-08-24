package com.jiapeng.labelreview.service;

import com.jiapeng.labelreview.api.ApiDtos.CreateProjectRequest;
import com.jiapeng.labelreview.api.ApiDtos.DecisionRequest;
import com.jiapeng.labelreview.api.ApiDtos.ProjectView;
import com.jiapeng.labelreview.api.ApiDtos.TaskImportRequest;
import com.jiapeng.labelreview.api.ApiDtos.TaskView;
import com.jiapeng.labelreview.domain.AppUser;
import com.jiapeng.labelreview.domain.DecisionType;
import com.jiapeng.labelreview.domain.TaskState;
import com.jiapeng.labelreview.domain.UserRole;
import com.jiapeng.labelreview.repository.TaskRepository;
import com.jiapeng.labelreview.repository.UserRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest
@Transactional
class TaskServiceIntegrationTests {

    @Autowired
    private UserRepository users;

    @Autowired
    private TaskRepository taskRepository;

    @Autowired
    private ProjectService projects;

    @Autowired
    private TaskService tasks;

    @TempDir
    Path reviewRoot;

    @Test
    void leasePreventsDuplicateClaimAndDecisionHonorsRecommendation() {
        AppUser admin = users.save(new AppUser("admin-test", "{noop}password", "Admin", UserRole.ADMIN));
        AppUser first = users.save(new AppUser("reviewer-a", "{noop}password", "Reviewer A", UserRole.REVIEWER));
        AppUser second = users.save(new AppUser("reviewer-b", "{noop}password", "Reviewer B", UserRole.REVIEWER));
        ProjectView project = projects.create(
                new CreateProjectRequest("lease-test", "integration", reviewRoot.toString()),
                admin);
        projects.importTasks(
                project.id(),
                List.of(new TaskImportRequest(
                        "R0001",
                        "train",
                        "sample.jpg",
                        "helmet",
                        0.91,
                        "GT0_AUTO1",
                        "accept_add_or_reject",
                        "visuals/sample.jpg")),
                admin);
        projects.assignMember(project.id(), first.getUsername(), admin);
        projects.assignMember(project.id(), second.getUsername(), admin);

        TaskView claimed = tasks.claimNext(project.id(), first).orElseThrow();

        assertThat(tasks.claimNext(project.id(), second)).isEmpty();
        assertThat(claimed.claimedBy()).isEqualTo(first.getUsername());
        assertThat(claimed.leaseUntil()).isNotNull();
        assertThatThrownBy(() -> tasks.decide(
                        claimed.id(),
                        new DecisionRequest(DecisionType.ACCEPT_REPLACE_GT, claimed.version(), "wrong action"),
                        first))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        exception -> assertThat(exception.getStatusCode()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY));

        TaskView completed = tasks.decide(
                claimed.id(),
                new DecisionRequest(DecisionType.ACCEPT_ADD, claimed.version(), "verified"),
                first);

        assertThat(completed.state()).isEqualTo(TaskState.COMPLETED);
        assertThat(taskRepository.countByProjectIdAndState(project.id(), TaskState.COMPLETED)).isOne();
    }

    @Test
    void staleClientVersionCannotOverwriteTask() {
        AppUser admin = users.save(new AppUser("admin-version", "{noop}password", "Admin", UserRole.ADMIN));
        AppUser reviewer = users.save(new AppUser("reviewer-version", "{noop}password", "Reviewer", UserRole.REVIEWER));
        ProjectView project = projects.create(
                new CreateProjectRequest("version-test", "integration", reviewRoot.toString()),
                admin);
        projects.importTasks(
                project.id(),
                List.of(new TaskImportRequest(
                        "R0002",
                        "val",
                        "sample.jpg",
                        "smoking",
                        0.72,
                        "GT0_AUTO1",
                        "add_or_reject",
                        "visuals/sample.jpg")),
                admin);
        projects.assignMember(project.id(), reviewer.getUsername(), admin);
        TaskView claimed = tasks.claimNext(project.id(), reviewer).orElseThrow();

        assertThatThrownBy(() -> tasks.decide(
                        claimed.id(),
                        new DecisionRequest(DecisionType.ACCEPT_ADD, claimed.version() - 1, "stale"),
                        reviewer))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        exception -> assertThat(exception.getStatusCode()).isEqualTo(HttpStatus.CONFLICT));
    }

    @Test
    void reviewerCannotClaimAnUnassignedProject() {
        AppUser admin = users.save(new AppUser("admin-scope", "{noop}password", "Admin", UserRole.ADMIN));
        AppUser outsider = users.save(new AppUser("reviewer-outsider", "{noop}password", "Outsider", UserRole.REVIEWER));
        ProjectView project = projects.create(
                new CreateProjectRequest("private-project", "integration", reviewRoot.toString()),
                admin);

        assertThatThrownBy(() -> tasks.claimNext(project.id(), outsider))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        exception -> assertThat(exception.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN));
    }
}
