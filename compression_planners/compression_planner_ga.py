#!/usr/bin/env python3
"""
Genetic Algorithm – Knapsack Problem (Message Compression Decisions)
=====================================================================
For each conversation position, find the optimal decision
(Keep / Compress / Throw) that minimises total cost while staying
within the weight capacity.

Problem
-------
  Positions  : 10 messages with roles and weights
  Decisions  : Keep  (DWF=1,   DCF=1)
               Compress(DWF=0.5, DCF=2)
               Throw (DWF=0,   DCF=3)
  Cost       : sum over i of  pos_i^4 x DCF[d]  +  THROW_AVERSION     x pos_i^4  (if Throw)
                                               +  KEEP_PREFERENCE   x (pos_i/N)^KEEP_CURVE x pos_i^4  (if not Keep)
                                               +  IMPORTANT_AVERSION x pos_i^4  (if Tool, Important=Y, not Keep)
               DWF only affects weight; aversion terms are dimensionless multipliers on pos^4
               KEEP_PREFERENCE peaks at the last position and fades toward zero for early positions
  Constraint : sum of  weight_i x DWF[d]  <=  max_capacity
  Fixed      : Position 1 must be Keep
"""

import random
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Problem definition
# ---------------------------------------------------------------------------

POSITIONS = list(range(1, 11))         # 1 … 10
ROLES     = [
    'System',    #  1
    'User',      #  2
    'Assistant', #  3
    'Tool',      #  4
    'Assistant', #  5
    'Tool',      #  6
    'Assistant', #  7
    'Tool',      #  8
    'User',      #  9
    'Tool',      # 10
]
WEIGHTS = [
     8,   #  1  System
     3,   #  2  User
     4,   #  3  Assistant
     7,   #  4  Tool
     5,   #  5  Assistant
     9,   #  6  Tool
     4,   #  7  Assistant
     8,   #  8  Tool
     2,   #  9  User
    10,   # 10  Tool
]
MAX_CAP = sum(WEIGHTS) // 2   # half of all-keep total

DECISIONS = ['Keep', 'Compress', 'Throw']
DWF       = [1.0, 0.5, 0.0]    # Decision Weight Factor
DCF       = [1,   2,   5  ]    # Decision Cost Factor
THROW_AVERSION     = 10           # multiplier on pos^4 added per Throw; weight-independent
KEEP_PREFERENCE    = 10           # peak multiplier on pos^4 for non-Keep (at last position)
KEEP_CURVE         = 2            # exponent for position-normalized curve (1=linear, 2=quadratic)
IMPORTANT_AVERSION = 15           # extra multiplier on pos^4 for not-Keeping an important Tool

# Importance flag — only meaningful for Tool positions; None = not applicable
IMPORTANT = [
    None,  #  1  System
    None,  #  2  User
    None,  #  3  Assistant
    True,  #  4  Tool   — Y
    None,  #  5  Assistant
    False, #  6  Tool   — N
    None,  #  7  Assistant
    True,  #  8  Tool   — Y
    None,  #  9  User
    True,  # 10  Tool   — Y
]

FIXED     = {0: 0}              # chromosome index -> forced decision (pos 1 = Keep)

# ---------------------------------------------------------------------------
# GA hyper-parameters
# ---------------------------------------------------------------------------

POP_SIZE         = 200
GENERATIONS      = 400
MUTATION_RATE    = 0.15
CROSSOVER_RATE   = 0.8
TOURNAMENT_SIZE  = 5
ELITE_COUNT      = 4
PENALTY_PER_UNIT = 10_000_000   # penalty per unit of excess weight

# ---------------------------------------------------------------------------
# Chromosome helpers
# ---------------------------------------------------------------------------

N = len(POSITIONS)
Chromosome = List[int]          # length N, each element in {0, 1, 2}


def _max_decision(i: int) -> int:
    """Return the highest allowed decision index for position i."""
    return 1 if IMPORTANT[i] else 2   # Important Tool: Keep/Compress only


def new_random() -> Chromosome:
    c = [random.randint(0, _max_decision(i)) for i in range(N)]
    for idx, dec in FIXED.items():
        c[idx] = dec
    return c


def repair(c: Chromosome) -> Chromosome:
    c = c.copy()
    for idx, dec in FIXED.items():
        c[idx] = dec
    for i in range(N):
        if c[i] > _max_decision(i):
            c[i] = _max_decision(i)
    return c


def eff_weight(c: Chromosome) -> float:
    return sum(WEIGHTS[i] * DWF[c[i]] for i in range(N))


def total_cost(c: Chromosome) -> float:
    return sum(
        (POSITIONS[i] ** 4) * DCF[c[i]]
        + (THROW_AVERSION     * POSITIONS[i] ** 4 if c[i] == 2 else 0)
        + (KEEP_PREFERENCE    * (POSITIONS[i] / POSITIONS[-1]) ** KEEP_CURVE * POSITIONS[i] ** 4 if c[i] != 0 else 0)
        + (IMPORTANT_AVERSION * POSITIONS[i] ** 4 if IMPORTANT[i] and c[i] != 0 else 0)
        for i in range(N)
    )


def fitness(c: Chromosome) -> float:
    """Higher is better. Infeasible chromosomes are penalised."""
    w    = eff_weight(c)
    base = -total_cost(c)                          # negate: maximise -cost = minimise cost
    if w > MAX_CAP:
        base -= (w - MAX_CAP) * PENALTY_PER_UNIT
    return base

# ---------------------------------------------------------------------------
# GA operators
# ---------------------------------------------------------------------------


def tournament(pop: List[Chromosome], fits: List[float]) -> Chromosome:
    idxs = random.sample(range(len(pop)), TOURNAMENT_SIZE)
    best = max(idxs, key=lambda i: fits[i])
    return pop[best].copy()


def crossover(p1: Chromosome, p2: Chromosome) -> Tuple[Chromosome, Chromosome]:
    if random.random() > CROSSOVER_RATE:
        return p1.copy(), p2.copy()
    pt = random.randint(1, N - 1)
    return repair(p1[:pt] + p2[pt:]), repair(p2[:pt] + p1[pt:])


def mutate(c: Chromosome) -> Chromosome:
    c = c.copy()
    for i in range(N):
        if i in FIXED:
            continue
        if random.random() < MUTATION_RATE:
            c[i] = random.randint(0, _max_decision(i))
    return c

# ---------------------------------------------------------------------------
# Main GA loop
# ---------------------------------------------------------------------------


def run_ga(seed: int = 42) -> Tuple[Chromosome, List[float]]:
    random.seed(seed)
    pop: List[Chromosome] = [new_random() for _ in range(POP_SIZE)]
    best_chrom = pop[0]
    best_fit   = float('-inf')
    log: List[float] = []

    for _ in range(GENERATIONS):
        fits = [fitness(c) for c in pop]

        top_idx = max(range(POP_SIZE), key=lambda i: fits[i])
        if fits[top_idx] > best_fit:
            best_fit   = fits[top_idx]
            best_chrom = pop[top_idx].copy()
        log.append(best_fit)

        # Elitism
        ranked  = sorted(range(POP_SIZE), key=lambda i: fits[i], reverse=True)
        new_pop = [pop[i].copy() for i in ranked[:ELITE_COUNT]]

        # Fill remainder via tournament + crossover + mutation
        while len(new_pop) < POP_SIZE:
            p1, p2 = tournament(pop, fits), tournament(pop, fits)
            c1, c2 = crossover(p1, p2)
            new_pop.append(mutate(c1))
            if len(new_pop) < POP_SIZE:
                new_pop.append(mutate(c2))

        pop = new_pop

    return best_chrom, log

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

W = 80


def print_solution(c: Chromosome) -> None:
    print()
    print("=" * W)
    print("  BEST SOLUTION")
    print("=" * W)
    print(f"  {'Pos':<5} {'Role':<12} {'Imp':<5} {'Wt':<5} {'Decision':<9} {'DWF':<6} {'DCF':<6} {'Pos^4':<8} {'Penalty':<12} {'DemandWt':<10} {'Cost'}")
    print("  " + "-" * (W - 2))
    total_w = 0.0
    total_c = 0.0
    for i in range(N):
        d       = c[i]
        pos     = POSITIONS[i]
        ew      = WEIGHTS[i] * DWF[d]
        p4      = pos ** 4
        curve   = (pos / POSITIONS[-1]) ** KEEP_CURVE
        imp_flag = IMPORTANT[i]
        imp_col  = ('-' if imp_flag is None else ('Y' if imp_flag else 'N'))
        penalty = (
            (THROW_AVERSION     * p4 if d == 2      else 0)
            + (KEEP_PREFERENCE  * curve * p4 if d != 0      else 0)
            + (IMPORTANT_AVERSION * p4 if imp_flag and d != 0 else 0)
        )
        gc      = p4 * DCF[d] + penalty
        total_w += ew
        total_c += gc
        note = "  <- fixed" if i in FIXED else ""
        print(f"  {pos:<5} {ROLES[i]:<12} {imp_col:<5} {WEIGHTS[i]:<5} {DECISIONS[d]:<9} {DWF[d]:<6} {DCF[d]:<6} {p4:<8} {penalty:<12.1f} {ew:<10.1f} {gc:.1f}{note}")
    print("  " + "-" * (W - 2))
    print(f"  {'TOTAL':<5} {'':<12} {'':<5} {'':<5} {'':<9} {'':<6} {'':<6} {'':<8} {'':<12} {total_w:<10.1f} {total_c:.1f}")
    print()
    feasible = total_w <= MAX_CAP
    print(f"  Capacity : {total_w:.1f} / {MAX_CAP}  ({'feasible' if feasible else 'INFEASIBLE'})")
    print(f"  Cost     : {total_c:.1f}")
    print("=" * W)


def print_convergence(log: List[float], step: int = 50) -> None:
    print("\n  Convergence (best fitness per generation):")
    print(f"  {'Gen':>5} | {'Fitness':>12}")
    print("  " + "-" * 22)
    for g in range(0, len(log), step):
        print(f"  {g:>5} | {log[g]:>12.1f}")
    print(f"  {len(log)-1:>5} | {log[-1]:>12.1f}")


# ---------------------------------------------------------------------------
# Public API – callable from other modules
# ---------------------------------------------------------------------------


def run_compression_planner(
    roles: List[str],
    weights: List[int],
    important: List,
    constraints: List[int] | None = None,
    seed: int = 42,
    max_cap: int | None = None,
    min_compress_group_tokens: int = 0,
) -> Tuple[List[str], bool, float]:
    """Return (decisions, feasible, eff_weight) where decisions is a per-message list of
    'Keep', 'Compress', or 'Throw', feasible is True if the best solution
    satisfies the weight capacity.

    Args:
        roles:       message roles, e.g. ['user', 'assistant', 'tool', ...]
        weights:     character lengths for each message
        important:   per-position importance flag — True/False for tool messages,
                     None for all others
        constraints: per-position max allowed decision — one value per message:
                       0 = Keep only
                       1 = Keep or Compress
                       2 = Keep, Compress, or Throw (default)
                     Falls back to important-based logic if None.
        seed:        random seed for reproducibility
        max_cap:     maximum allowed effective weight; defaults to sum(weights) // 2
    """
    n         = len(roles)
    positions = list(range(1, n + 1))
    max_cap   = sum(weights) // 2 if max_cap is None else max_cap

    # ---- helpers (closures over local n / positions / weights / important / max_cap) ----

    def _max_dec(i: int) -> int:
        if constraints is not None:
            return constraints[i]
        return 1 if important[i] else 2

    def _new_random() -> Chromosome:
        return [random.randint(0, _max_dec(i)) for i in range(n)]

    def _repair(c: Chromosome) -> Chromosome:
        c = c.copy()
        for i in range(n):
            if c[i] > _max_dec(i):
                c[i] = _max_dec(i)
        return c

    def _eff_weight(c: Chromosome) -> float:
        return sum(weights[i] * DWF[c[i]] for i in range(n))

    def _total_cost(c: Chromosome) -> float:
        return sum(
            (positions[i] ** 4) * DCF[c[i]]
            + (THROW_AVERSION     * positions[i] ** 4 if c[i] == 2 else 0)
            + (KEEP_PREFERENCE    * (positions[i] / positions[-1]) ** KEEP_CURVE * positions[i] ** 4 if c[i] != 0 else 0)
            + (IMPORTANT_AVERSION * positions[i] ** 4 if important[i] and c[i] != 0 else 0)
            for i in range(n)
        )

    def _fitness(c: Chromosome) -> float:
        w    = _eff_weight(c)
        base = -_total_cost(c)
        if w > max_cap:
            base -= (w - max_cap) * PENALTY_PER_UNIT
        return base

    def _tournament(pop: List[Chromosome], fits: List[float]) -> Chromosome:
        idxs = random.sample(range(len(pop)), TOURNAMENT_SIZE)
        best = max(idxs, key=lambda i: fits[i])
        return pop[best].copy()

    def _crossover(p1: Chromosome, p2: Chromosome) -> Tuple[Chromosome, Chromosome]:
        if n < 2 or random.random() > CROSSOVER_RATE:
            return p1.copy(), p2.copy()
        pt = random.randint(1, n - 1)
        return _repair(p1[:pt] + p2[pt:]), _repair(p2[:pt] + p1[pt:])

    def _mutate(c: Chromosome) -> Chromosome:
        c = c.copy()
        for i in range(n):
            if random.random() < MUTATION_RATE:
                c[i] = random.randint(0, _max_dec(i))
        return c

    def _enforce_compress_groups(c: Chromosome) -> Chromosome:
        c = c.copy()
        i = 0
        while i < n:
            if c[i] == 1:          # start of a Compress run
                j = i
                while j < n and c[j] == 1:
                    j += 1
                if sum(weights[k] for k in range(i, j)) < min_compress_group_tokens:
                    for k in range(i, j):
                        c[k] = 0   # revert to Keep
                i = j
            else:
                i += 1
        return c

    # ---- GA loop ----
    random.seed(seed)
    pop: List[Chromosome] = [_enforce_compress_groups(_new_random()) for _ in range(POP_SIZE)]
    best_chrom = pop[0]
    best_fit   = float('-inf')

    for _ in range(GENERATIONS):
        fits = [_fitness(c) for c in pop]
        top_idx = max(range(POP_SIZE), key=lambda i: fits[i])
        if fits[top_idx] > best_fit:
            best_fit   = fits[top_idx]
            best_chrom = _enforce_compress_groups(pop[top_idx].copy())

        ranked  = sorted(range(POP_SIZE), key=lambda i: fits[i], reverse=True)
        new_pop = [_enforce_compress_groups(pop[i].copy()) for i in ranked[:ELITE_COUNT]]
        while len(new_pop) < POP_SIZE:
            p1, p2 = _tournament(pop, fits), _tournament(pop, fits)
            c1, c2 = _crossover(p1, p2)
            new_pop.append(_enforce_compress_groups(_mutate(c1)))
            if len(new_pop) < POP_SIZE:
                new_pop.append(_enforce_compress_groups(_mutate(c2)))
        pop = new_pop

    eff_w    = _eff_weight(best_chrom)
    feasible = eff_w <= max_cap
    return [DECISIONS[best_chrom[i]] for i in range(n)], feasible, eff_w


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("Running genetic algorithm ...")
    constraints = [0] + [2] * (len(ROLES) - 1)   # position 0 forced Keep
    decisions, feasible = run_compression_planner(ROLES, WEIGHTS, IMPORTANT, constraints=constraints)
    print(f"  Feasible: {feasible}")
    # Reconstruct a chromosome for the existing print helpers
    best = [DECISIONS.index(d) for d in decisions]
    print_solution(best)
    best_old, log = run_ga()
    print_convergence(log)
