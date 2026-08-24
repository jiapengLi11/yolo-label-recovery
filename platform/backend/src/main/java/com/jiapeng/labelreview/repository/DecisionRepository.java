package com.jiapeng.labelreview.repository;

import com.jiapeng.labelreview.domain.ReviewDecision;
import org.springframework.data.jpa.repository.JpaRepository;

public interface DecisionRepository extends JpaRepository<ReviewDecision, Long> {
    boolean existsByTaskId(Long taskId);
}
