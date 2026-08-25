package com.jiapeng.labelreview.service;

import com.jiapeng.labelreview.domain.DecisionType;

import java.util.Map;
import java.util.Set;

public final class DecisionPolicy {

    private static final Map<String, Set<DecisionType>> ALLOWED = Map.of(
            "accept_add_or_reject", Set.of(DecisionType.ACCEPT_ADD, DecisionType.REJECT, DecisionType.UNCERTAIN),
            "add_or_reject", Set.of(DecisionType.ACCEPT_ADD, DecisionType.REJECT, DecisionType.UNCERTAIN),
            "replace_or_reject", Set.of(DecisionType.ACCEPT_REPLACE_GT, DecisionType.REJECT, DecisionType.UNCERTAIN),
            "accept_eval_or_reject", Set.of(DecisionType.ACCEPT_EVAL_LABEL, DecisionType.REJECT, DecisionType.UNCERTAIN));

    private DecisionPolicy() {
    }

    public static boolean isAllowed(String recommendedAction, DecisionType decision) {
        return ALLOWED.getOrDefault(
                        recommendedAction,
                        Set.of(DecisionType.REJECT, DecisionType.UNCERTAIN))
                .contains(decision);
    }
}
