package com.jiapeng.labelreview.config;

import jakarta.validation.constraints.Min;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties(prefix = "app.review")
public record ReviewProperties(@Min(1) long leaseMinutes) {
}
