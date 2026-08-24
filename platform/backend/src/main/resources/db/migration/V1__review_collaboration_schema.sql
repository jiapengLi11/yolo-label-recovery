CREATE TABLE app_users (
    id BIGINT NOT NULL AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP(6) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_app_users_username UNIQUE (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE review_projects (
    id BIGINT NOT NULL AUTO_INCREMENT,
    name VARCHAR(120) NOT NULL,
    description VARCHAR(500) NOT NULL,
    review_root VARCHAR(1000) NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP(6) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_review_projects_creator FOREIGN KEY (created_by) REFERENCES app_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE project_members (
    id BIGINT NOT NULL AUTO_INCREMENT,
    project_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    assigned_by BIGINT NOT NULL,
    assigned_at TIMESTAMP(6) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_project_member UNIQUE (project_id, user_id),
    CONSTRAINT fk_project_members_project FOREIGN KEY (project_id) REFERENCES review_projects (id),
    CONSTRAINT fk_project_members_user FOREIGN KEY (user_id) REFERENCES app_users (id),
    CONSTRAINT fk_project_members_assigner FOREIGN KEY (assigned_by) REFERENCES app_users (id),
    INDEX ix_project_members_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE review_tasks (
    id BIGINT NOT NULL AUTO_INCREMENT,
    project_id BIGINT NOT NULL,
    candidate_id VARCHAR(80) NOT NULL,
    split VARCHAR(20) NOT NULL,
    image_name VARCHAR(500) NOT NULL,
    class_name VARCHAR(80) NOT NULL,
    confidence DOUBLE NOT NULL,
    case_code VARCHAR(80) NOT NULL,
    recommended_action VARCHAR(80) NOT NULL,
    visual_file VARCHAR(1000) NOT NULL,
    state VARCHAR(20) NOT NULL,
    claimed_by BIGINT NULL,
    lease_until TIMESTAMP(6) NULL,
    created_at TIMESTAMP(6) NOT NULL,
    updated_at TIMESTAMP(6) NOT NULL,
    version BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT uk_review_task_candidate UNIQUE (project_id, candidate_id),
    CONSTRAINT fk_review_tasks_project FOREIGN KEY (project_id) REFERENCES review_projects (id),
    CONSTRAINT fk_review_tasks_reviewer FOREIGN KEY (claimed_by) REFERENCES app_users (id),
    INDEX ix_review_tasks_claim (project_id, state, lease_until, id),
    INDEX ix_review_tasks_reviewer (claimed_by, state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE review_decisions (
    id BIGINT NOT NULL AUTO_INCREMENT,
    task_id BIGINT NOT NULL,
    reviewer_id BIGINT NOT NULL,
    decision VARCHAR(40) NOT NULL,
    comment VARCHAR(1000) NOT NULL,
    decided_at TIMESTAMP(6) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_review_decisions_task UNIQUE (task_id),
    CONSTRAINT fk_review_decisions_task FOREIGN KEY (task_id) REFERENCES review_tasks (id),
    CONSTRAINT fk_review_decisions_reviewer FOREIGN KEY (reviewer_id) REFERENCES app_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE audit_events (
    id BIGINT NOT NULL AUTO_INCREMENT,
    actor VARCHAR(64) NOT NULL,
    action VARCHAR(80) NOT NULL,
    resource_type VARCHAR(80) NOT NULL,
    resource_id VARCHAR(100) NOT NULL,
    details VARCHAR(2000) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL,
    PRIMARY KEY (id),
    INDEX ix_audit_resource_time (resource_type, resource_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
