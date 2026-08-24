package com.jiapeng.labelreview.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.Version;

import java.time.Instant;

@Entity
@Table(name = "review_tasks")
public class ReviewTask {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "project_id", nullable = false)
    private ReviewProject project;

    @Column(name = "candidate_id", nullable = false, length = 80)
    private String candidateId;

    @Column(nullable = false, length = 20)
    private String split;

    @Column(name = "image_name", nullable = false, length = 500)
    private String imageName;

    @Column(name = "class_name", nullable = false, length = 80)
    private String className;

    @Column(nullable = false)
    private double confidence;

    @Column(name = "case_code", nullable = false, length = 80)
    private String caseCode;

    @Column(name = "recommended_action", nullable = false, length = 80)
    private String recommendedAction;

    @Column(name = "visual_file", nullable = false, length = 1000)
    private String visualFile;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private TaskState state = TaskState.PENDING;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "claimed_by")
    private AppUser claimedBy;

    @Column(name = "lease_until")
    private Instant leaseUntil;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt = Instant.now();

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt = Instant.now();

    @Version
    @Column(nullable = false)
    private long version;

    protected ReviewTask() {
    }

    public ReviewTask(
            ReviewProject project,
            String candidateId,
            String split,
            String imageName,
            String className,
            double confidence,
            String caseCode,
            String recommendedAction,
            String visualFile) {
        this.project = project;
        this.candidateId = candidateId;
        this.split = split;
        this.imageName = imageName;
        this.className = className;
        this.confidence = confidence;
        this.caseCode = caseCode;
        this.recommendedAction = recommendedAction;
        this.visualFile = visualFile;
    }

    public Long getId() {
        return id;
    }

    public ReviewProject getProject() {
        return project;
    }

    public String getCandidateId() {
        return candidateId;
    }

    public String getSplit() {
        return split;
    }

    public String getImageName() {
        return imageName;
    }

    public String getClassName() {
        return className;
    }

    public double getConfidence() {
        return confidence;
    }

    public String getCaseCode() {
        return caseCode;
    }

    public String getRecommendedAction() {
        return recommendedAction;
    }

    public String getVisualFile() {
        return visualFile;
    }

    public TaskState getState() {
        return state;
    }

    public AppUser getClaimedBy() {
        return claimedBy;
    }

    public Instant getLeaseUntil() {
        return leaseUntil;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public long getVersion() {
        return version;
    }

    public void claim(AppUser reviewer, Instant leaseUntil) {
        this.claimedBy = reviewer;
        this.leaseUntil = leaseUntil;
        this.state = TaskState.CLAIMED;
        touch();
    }

    public void extendLease(Instant leaseUntil) {
        this.leaseUntil = leaseUntil;
        touch();
    }

    public void release() {
        this.claimedBy = null;
        this.leaseUntil = null;
        this.state = TaskState.PENDING;
        touch();
    }

    public void complete(boolean escalated) {
        this.state = escalated ? TaskState.ESCALATED : TaskState.COMPLETED;
        this.leaseUntil = null;
        touch();
    }

    private void touch() {
        this.updatedAt = Instant.now();
    }
}
