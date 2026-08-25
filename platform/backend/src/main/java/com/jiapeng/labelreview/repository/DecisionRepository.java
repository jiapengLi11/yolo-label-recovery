package com.jiapeng.labelreview.repository;

import com.jiapeng.labelreview.domain.ReviewDecision;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.Collection;
import java.util.List;

public interface DecisionRepository extends JpaRepository<ReviewDecision, Long> {
    boolean existsByTaskId(Long taskId);

    @Query("select d.task.id from ReviewDecision d where d.task.project.id = :projectId and d.task.candidateId in :candidateIds")
    List<Long> findTaskIdsByProjectAndCandidateIds(
            @Param("projectId") Long projectId,
            @Param("candidateIds") Collection<String> candidateIds);
}
