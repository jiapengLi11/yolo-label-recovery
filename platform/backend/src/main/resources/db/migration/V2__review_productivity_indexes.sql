CREATE INDEX ix_review_tasks_image_group
    ON review_tasks (project_id, split, image_name, id);

CREATE INDEX ix_review_decisions_reviewer_time
    ON review_decisions (reviewer_id, decided_at, id);
