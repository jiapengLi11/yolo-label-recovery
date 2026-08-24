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
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;

import java.time.Instant;

@Entity
@Table(name = "review_decisions")
public class ReviewDecision {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @OneToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "task_id", nullable = false, unique = true)
    private ReviewTask task;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "reviewer_id", nullable = false)
    private AppUser reviewer;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 40)
    private DecisionType decision;

    @Column(nullable = false, length = 1000)
    private String comment;

    @Column(name = "decided_at", nullable = false, updatable = false)
    private Instant decidedAt = Instant.now();

    protected ReviewDecision() {
    }

    public ReviewDecision(ReviewTask task, AppUser reviewer, DecisionType decision, String comment) {
        this.task = task;
        this.reviewer = reviewer;
        this.decision = decision;
        this.comment = comment;
    }

    public Long getId() {
        return id;
    }

    public ReviewTask getTask() {
        return task;
    }

    public AppUser getReviewer() {
        return reviewer;
    }

    public DecisionType getDecision() {
        return decision;
    }

    public String getComment() {
        return comment;
    }

    public Instant getDecidedAt() {
        return decidedAt;
    }
}
