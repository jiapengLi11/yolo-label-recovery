package com.jiapeng.labelreview.service;

import com.jiapeng.labelreview.domain.AuditEvent;
import com.jiapeng.labelreview.api.ApiDtos.AuditView;
import com.jiapeng.labelreview.repository.AuditEventRepository;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class AuditService {

    private final AuditEventRepository events;

    public AuditService(AuditEventRepository events) {
        this.events = events;
    }

    public void record(String actor, String action, String resourceType, Object resourceId, String details) {
        events.save(new AuditEvent(actor, action, resourceType, String.valueOf(resourceId), details));
    }

    public List<AuditView> listProjectEvents(Long projectId, int limit) {
        return events.findByResourceTypeAndResourceIdOrderByCreatedAtDesc(
                        "PROJECT",
                        String.valueOf(projectId),
                        PageRequest.of(0, Math.min(Math.max(limit, 1), 500)))
                .stream()
                .map(event -> new AuditView(
                        event.getId(),
                        event.getActor(),
                        event.getAction(),
                        event.getResourceType(),
                        event.getResourceId(),
                        event.getDetails(),
                        event.getCreatedAt()))
                .toList();
    }
}
