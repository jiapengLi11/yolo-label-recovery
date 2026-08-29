package com.jiapeng.labelreview.repository;

import com.jiapeng.labelreview.domain.ReviewDecision;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.domain.Pageable;
import org.springframework.data.repository.query.Param;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface DecisionRepository extends JpaRepository<ReviewDecision, Long> {
    boolean existsByTaskId(Long taskId);

    Optional<ReviewDecision> findByTaskId(Long taskId);

    List<ReviewDecision> findByTaskIdIn(Collection<Long> taskIds);

    @Query("""
            select d from ReviewDecision d
            join fetch d.task t
            where d.reviewer.id = :reviewerId and t.project.id = :projectId
            order by d.decidedAt desc, d.id desc
            """)
    List<ReviewDecision> findRecentByReviewerAndProject(
            @Param("reviewerId") Long reviewerId,
            @Param("projectId") Long projectId,
            Pageable pageable);

    @Query("select d.task.id from ReviewDecision d where d.task.project.id = :projectId and d.task.candidateId in :candidateIds")
    List<Long> findTaskIdsByProjectAndCandidateIds(
            @Param("projectId") Long projectId,
            @Param("candidateIds") Collection<String> candidateIds);
}
