package com.jiapeng.labelreview.api;

import com.jiapeng.labelreview.domain.DecisionType;
import com.jiapeng.labelreview.domain.ProjectStatus;
import com.jiapeng.labelreview.domain.TaskState;
import com.jiapeng.labelreview.domain.UserRole;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.time.Instant;

public final class ApiDtos {

    private ApiDtos() {
    }

    public record LoginRequest(@NotBlank String username, @NotBlank String password) {
    }

    public record AuthResponse(String accessToken, Instant expiresAt, UserView user) {
    }

    public record UserView(Long id, String username, String displayName, UserRole role, boolean enabled) {
    }

    public record CreateUserRequest(
            @NotBlank @Size(max = 64) String username,
            @NotBlank @Size(min = 12, max = 128) String password,
            @NotBlank @Size(max = 100) String displayName,
            @NotNull UserRole role) {
    }

    public record CreateProjectRequest(
            @NotBlank @Size(max = 120) String name,
            @Size(max = 500) String description,
            @NotBlank @Size(max = 1000) String reviewRoot) {
    }

    public record ProjectView(
            Long id,
            String name,
            String description,
            ProjectStatus status,
            String createdBy,
            Instant createdAt) {
    }

    public record ProjectMemberRequest(@NotBlank @Size(max = 64) String username) {
    }

    public record ProjectMemberView(
            Long id,
            Long userId,
            String username,
            String displayName,
            UserRole role,
            String assignedBy,
            Instant assignedAt) {
    }

    public record TaskImportRequest(
            @NotBlank @Size(max = 80) String candidateId,
            @NotBlank @Size(max = 20) String split,
            @NotBlank @Size(max = 500) String imageName,
            @NotBlank @Size(max = 80) String className,
            @DecimalMin("0.0") @DecimalMax("1.0") double confidence,
            @NotBlank @Size(max = 80) String caseCode,
            @NotBlank @Size(max = 80) String recommendedAction,
            @NotBlank @Size(max = 1000) String visualFile) {
    }

    public record ImportResult(int received, int created, int skippedExisting) {
    }

    public record HistoricalDecisionImportRequest(
            @NotBlank @Size(max = 80) String candidateId,
            @NotNull DecisionType decision,
            @Size(max = 1000) String comment) {
    }

    public record HistoricalDecisionImportResult(
            int received,
            int imported,
            int skippedExisting,
            int unknownCandidates,
            int invalidDecisions) {
    }

    public record TaskView(
            Long id,
            long version,
            Long projectId,
            String candidateId,
            String split,
            String imageName,
            String className,
            double confidence,
            String caseCode,
            String recommendedAction,
            TaskState state,
            String claimedBy,
            Instant leaseUntil,
            String visualUrl) {
    }

    public record DecisionRequest(
            @NotNull DecisionType decision,
            @NotNull Long expectedVersion,
            @Size(max = 1000) String comment) {
    }

    public record ProgressView(
            long total,
            long pending,
            long claimed,
            long completed,
            long escalated,
            double completionRate) {
    }

    public record AuditView(
            Long id,
            String actor,
            String action,
            String resourceType,
            String resourceId,
            String details,
            Instant createdAt) {
    }
}
