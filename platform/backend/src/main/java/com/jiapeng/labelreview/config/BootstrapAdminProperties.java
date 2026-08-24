package com.jiapeng.labelreview.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app.bootstrap-admin")
public record BootstrapAdminProperties(
        boolean enabled,
        String username,
        String password,
        String displayName) {
}
