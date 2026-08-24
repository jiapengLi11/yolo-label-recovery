package com.jiapeng.labelreview.service;

import com.jiapeng.labelreview.config.BootstrapAdminProperties;
import com.jiapeng.labelreview.domain.AppUser;
import com.jiapeng.labelreview.domain.UserRole;
import com.jiapeng.labelreview.repository.UserRepository;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

import java.util.Locale;

@Component
public class BootstrapAdmin implements ApplicationRunner {

    private final BootstrapAdminProperties properties;
    private final UserRepository users;
    private final PasswordEncoder encoder;

    public BootstrapAdmin(BootstrapAdminProperties properties, UserRepository users, PasswordEncoder encoder) {
        this.properties = properties;
        this.users = users;
        this.encoder = encoder;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (!properties.enabled()) {
            return;
        }
        if (properties.username() == null || properties.password() == null || properties.password().length() < 12) {
            throw new IllegalStateException("Bootstrap admin requires a username and a password of at least 12 characters");
        }
        String username = properties.username().trim().toLowerCase(Locale.ROOT);
        if (!users.existsByUsername(username)) {
            String displayName = properties.displayName() == null ? username : properties.displayName().trim();
            users.save(new AppUser(
                    username,
                    encoder.encode(properties.password()),
                    displayName,
                    UserRole.ADMIN));
        }
    }
}
