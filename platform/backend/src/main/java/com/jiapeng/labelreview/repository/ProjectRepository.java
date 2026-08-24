package com.jiapeng.labelreview.repository;

import com.jiapeng.labelreview.domain.ReviewProject;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProjectRepository extends JpaRepository<ReviewProject, Long> {
}
