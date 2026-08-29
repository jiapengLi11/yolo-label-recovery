package com.jiapeng.labelreview.repository;

import com.jiapeng.labelreview.domain.ReviewTask;
import com.jiapeng.labelreview.domain.TaskState;
import jakarta.persistence.LockModeType;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface TaskRepository extends JpaRepository<ReviewTask, Long> {

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("""
            select t from ReviewTask t
            where t.project.id = :projectId
              and t.project.status = com.jiapeng.labelreview.domain.ProjectStatus.OPEN
              and (t.state = com.jiapeng.labelreview.domain.TaskState.PENDING
                   or (t.state = com.jiapeng.labelreview.domain.TaskState.CLAIMED and t.leaseUntil < :now))
            order by t.id
            """)
    List<ReviewTask> findClaimable(
            @Param("projectId") Long projectId,
            @Param("now") Instant now,
            Pageable pageable);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select t from ReviewTask t join fetch t.project left join fetch t.claimedBy where t.id = :id")
    Optional<ReviewTask> findByIdForUpdate(@Param("id") Long id);

    @Query("select t.candidateId from ReviewTask t where t.project.id = :projectId and t.candidateId in :candidateIds")
    List<String> findExistingCandidateIds(
            @Param("projectId") Long projectId,
            @Param("candidateIds") Collection<String> candidateIds);

    @Query("select t from ReviewTask t where t.project.id = :projectId and t.candidateId in :candidateIds")
    List<ReviewTask> findByProjectIdAndCandidateIds(
            @Param("projectId") Long projectId,
            @Param("candidateIds") Collection<String> candidateIds);

    Optional<ReviewTask> findFirstByClaimedByUsernameAndStateOrderByUpdatedAtDesc(String username, TaskState state);

    List<ReviewTask> findByProjectIdAndSplitAndImageNameOrderById(Long projectId, String split, String imageName);

    long countByProjectId(Long projectId);

    long countByProjectIdAndState(Long projectId, TaskState state);
}
