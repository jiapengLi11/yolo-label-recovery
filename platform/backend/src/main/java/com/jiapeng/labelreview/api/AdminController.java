package com.jiapeng.labelreview.api;

import com.jiapeng.labelreview.api.ApiDtos.CreateUserRequest;
import com.jiapeng.labelreview.api.ApiDtos.UserView;
import com.jiapeng.labelreview.domain.AppUser;
import com.jiapeng.labelreview.service.CurrentUserService;
import com.jiapeng.labelreview.service.UserService;
import jakarta.validation.Valid;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/admin/users")
@PreAuthorize("hasRole('ADMIN')")
public class AdminController {

    private final UserService users;
    private final CurrentUserService currentUsers;

    public AdminController(UserService users, CurrentUserService currentUsers) {
        this.users = users;
        this.currentUsers = currentUsers;
    }

    @GetMapping
    public List<UserView> list() {
        return users.list();
    }

    @PostMapping
    public UserView create(@Valid @RequestBody CreateUserRequest request, Authentication authentication) {
        AppUser actor = currentUsers.require(authentication);
        return users.create(request, actor);
    }
}
