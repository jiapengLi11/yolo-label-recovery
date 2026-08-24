package com.jiapeng.labelreview.api;

import com.jiapeng.labelreview.api.ApiDtos.AuthResponse;
import com.jiapeng.labelreview.api.ApiDtos.LoginRequest;
import com.jiapeng.labelreview.api.ApiDtos.UserView;
import com.jiapeng.labelreview.domain.AppUser;
import com.jiapeng.labelreview.repository.UserRepository;
import com.jiapeng.labelreview.service.CurrentUserService;
import com.jiapeng.labelreview.service.TokenService;
import com.jiapeng.labelreview.service.UserService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.Locale;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthenticationManager authenticationManager;
    private final UserRepository users;
    private final TokenService tokens;
    private final CurrentUserService currentUsers;

    public AuthController(
            AuthenticationManager authenticationManager,
            UserRepository users,
            TokenService tokens,
            CurrentUserService currentUsers) {
        this.authenticationManager = authenticationManager;
        this.users = users;
        this.tokens = tokens;
        this.currentUsers = currentUsers;
    }

    @PostMapping("/login")
    public AuthResponse login(@Valid @RequestBody LoginRequest request) {
        String username = request.username().trim().toLowerCase(Locale.ROOT);
        authenticationManager.authenticate(new UsernamePasswordAuthenticationToken(username, request.password()));
        AppUser user = users.findByUsername(username)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid credentials"));
        TokenService.IssuedToken token = tokens.issue(user);
        return new AuthResponse(token.value(), token.expiresAt(), UserService.view(user));
    }

    @GetMapping("/me")
    public UserView me(Authentication authentication) {
        return UserService.view(currentUsers.require(authentication));
    }
}
