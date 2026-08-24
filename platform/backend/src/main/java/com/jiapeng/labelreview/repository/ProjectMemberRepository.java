package com.jiapeng.labelreview.repository;

import com.jiapeng.labelreview.domain.ProjectMember;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ProjectMemberRepository extends JpaRepository<ProjectMember, Long> {

    boolean existsByProjectIdAndUserId(Long projectId, Long userId);

    List<ProjectMember> findByProjectIdOrderByAssignedAt(Long projectId);

    List<ProjectMember> findByUserIdOrderByAssignedAt(Long userId);
}
