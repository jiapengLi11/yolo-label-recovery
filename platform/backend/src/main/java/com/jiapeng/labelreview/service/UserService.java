package com.jiapeng.labelreview.service;

import com.jiapeng.labelreview.api.ApiDtos.CreateUserRequest;
import com.jiapeng.labelreview.api.ApiDtos.UserView;
import com.jiapeng.labelreview.domain.AppUser;
import com.jiapeng.labelreview.repository.UserRepository;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Locale;

@Service
public class UserService {

    private final UserRepository users;
    private final PasswordEncoder encoder;
    private final AuditService audit;

    public UserService(UserRepository users, PasswordEncoder encoder, AuditService audit) {
        this.users = users;
        this.encoder = encoder;
        this.audit = audit;
    }

    @Transactional
    public UserView create(CreateUserRequest request, AppUser actor) {
        String username = request.username().trim().toLowerCase(Locale.ROOT);
        if (users.existsByUsername(username)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Username already exists");
        }
        AppUser user = users.save(new AppUser(
                username,
                encoder.encode(request.password()),
                request.displayName().trim(),
                request.role()));
        audit.record(actor.getUsername(), "USER_CREATED", "USER", user.getId(), "role=" + user.getRole());
        return view(user);
    }

    @Transactional(readOnly = true)
    public List<UserView> list() {
        return users.findAll().stream().map(UserService::view).toList();
    }

    public static UserView view(AppUser user) {
        return new UserView(
                user.getId(),
                user.getUsername(),
                user.getDisplayName(),
                user.getRole(),
                user.isEnabled());
    }
}
