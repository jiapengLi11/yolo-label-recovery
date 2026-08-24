package com.jiapeng.labelreview;

import com.jiapeng.labelreview.config.JwtProperties;
import com.jiapeng.labelreview.config.ReviewProperties;
import com.jiapeng.labelreview.config.BootstrapAdminProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties({JwtProperties.class, ReviewProperties.class, BootstrapAdminProperties.class})
public class LabelReviewApplication {

    public static void main(String[] args) {
        SpringApplication.run(LabelReviewApplication.class, args);
    }
}
