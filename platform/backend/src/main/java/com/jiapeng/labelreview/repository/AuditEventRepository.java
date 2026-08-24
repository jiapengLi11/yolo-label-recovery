package com.jiapeng.labelreview.repository;

import com.jiapeng.labelreview.domain.AuditEvent;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AuditEventRepository extends JpaRepository<AuditEvent, Long> {
    Page<AuditEvent> findByResourceTypeAndResourceIdOrderByCreatedAtDesc(
            String resourceType,
            String resourceId,
            Pageable pageable);
}
