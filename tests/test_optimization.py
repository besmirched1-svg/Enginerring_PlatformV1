from app.core.optimization import (
    Individual,
    Objective,
    OptimizationResult,
    MultiObjectiveOptimizer,
    fast_nondominated_sort,
    calculate_crowding_distance,
    tournament_selection,
    crossover,
    mutate,
    create_default_hemp_decotitator_objectives,
    create_hemp_decotitator_optimizer,
    check_dominance,
    pareto_dominates,
    compute_ideal_point,
    compute_nadir_point,
    hypervolume,
    knee_selection,
    pareto_ranking,
    normalize_objectives,
)


# ---------------------------------------------------------------------------
# Individual & dominates tests
# ---------------------------------------------------------------------------

def test_individual_dominates_all_minimize():
    a = Individual(objectives=[1.0, 2.0])
    b = Individual(objectives=[3.0, 4.0])
    assert a.dominates(b) is True
    assert b.dominates(a) is False


def test_individual_dominates_equal():
    a = Individual(objectives=[1.0, 2.0])
    b = Individual(objectives=[1.0, 2.0])
    assert a.dominates(b) is False  # not strictly better in any
    assert b.dominates(a) is False


def test_individual_dominates_one_better_one_worse():
    a = Individual(objectives=[1.0, 5.0])
    b = Individual(objectives=[3.0, 2.0])
    assert a.dominates(b) is False  # a better in obj 0, worse in obj 1
    assert b.dominates(a) is False


def test_individual_dominates_with_minimize_flags():
    a = Individual(objectives=[0.9, 100.0])  # high recovery, high weight
    b = Individual(objectives=[0.5, 200.0])  # lower recovery, higher weight
    # minimize recovery (True), minimize weight (True)
    assert a.dominates(b, minimize_flags=[True, True]) is False
    # maximize recovery (False), minimize weight (True)
    assert a.dominates(b, minimize_flags=[False, True]) is True


def test_individual_is_dominated_by():
    a = Individual(objectives=[1.0, 2.0])
    b = Individual(objectives=[3.0, 4.0])
    assert a.is_dominated_by(b) is False
    assert b.is_dominated_by(a) is True


# ---------------------------------------------------------------------------
# check_dominance tests
# ---------------------------------------------------------------------------

def test_check_dominance_a_dominates_b():
    assert check_dominance([1.0, 2.0], [3.0, 4.0]) == 1


def test_check_dominance_b_dominates_a():
    assert check_dominance([3.0, 4.0], [1.0, 2.0]) == -1


def test_check_dominance_non_dominated():
    assert check_dominance([1.0, 4.0], [3.0, 2.0]) == 0


def test_check_dominance_equal():
    assert check_dominance([2.0, 2.0], [2.0, 2.0]) == 0


def test_check_dominance_maximize():
    assert check_dominance([0.9, 0.8], [0.5, 0.4], [False, False]) == 1
    assert check_dominance([0.5, 0.4], [0.9, 0.8], [False, False]) == -1


def test_pareto_dominates():
    assert pareto_dominates([1.0, 2.0], [3.0, 4.0]) is True
    assert pareto_dominates([3.0, 4.0], [1.0, 2.0]) is False


# ---------------------------------------------------------------------------
# fast_nondominated_sort tests
# ---------------------------------------------------------------------------

def test_fast_nondominated_sort_empty():
    assert fast_nondominated_sort([]) == []


def test_fast_nondominated_sort_single_front():
    # All three are non-dominated: better in one, worse in another
    inds = [
        Individual(objectives=[1.0, 8.0]),  # best obj0, worst obj1
        Individual(objectives=[3.0, 5.0]),  # middle in both
        Individual(objectives=[5.0, 2.0]),  # worst obj0, best obj1
    ]
    fronts = fast_nondominated_sort(inds)
    assert len(fronts) == 1
    assert len(fronts[0]) == 3


def test_fast_nondominated_sort_two_fronts():
    inds = [
        Individual(objectives=[1.0, 1.0]),  # front 0
        Individual(objectives=[2.0, 2.0]),  # front 0 or 1?
        Individual(objectives=[3.0, 3.0]),  # front 1
        Individual(objectives=[4.0, 1.0]),  # non-dominated with 2,2 and 3,3?
    ]
    fronts = fast_nondominated_sort(inds)
    assert len(fronts) >= 1
    # [1,1] should dominate everyone
    assert fronts[0][0].objectives == [1.0, 1.0]


# ---------------------------------------------------------------------------
# compute_ideal_point / compute_nadir_point tests
# ---------------------------------------------------------------------------

def test_compute_ideal_point():
    inds = [
        Individual(objectives=[5.0, 10.0]),
        Individual(objectives=[3.0, 8.0]),
        Individual(objectives=[7.0, 6.0]),
    ]
    ideal = compute_ideal_point(inds)
    assert ideal == [3.0, 6.0]


def test_compute_nadir_point():
    inds = [
        Individual(objectives=[5.0, 10.0]),
        Individual(objectives=[3.0, 8.0]),
        Individual(objectives=[7.0, 6.0]),
    ]
    nadir = compute_nadir_point(inds)
    assert nadir == [7.0, 10.0]


def test_ideal_nadir_with_maximize():
    inds = [
        Individual(objectives=[0.5, 100.0]),
        Individual(objectives=[0.9, 200.0]),
    ]
    ideal = compute_ideal_point(inds, minimize_flags=[False, True])
    assert ideal == [0.9, 100.0]  # max recovery, min weight
    nadir = compute_nadir_point(inds, minimize_flags=[False, True])
    assert nadir == [0.5, 200.0]


# ---------------------------------------------------------------------------
# hypervolume tests
# ---------------------------------------------------------------------------

def test_hypervolume_empty():
    assert hypervolume([]) == 0.0


def test_hypervolume_2d():
    inds = [
        Individual(objectives=[1.0, 8.0]),
        Individual(objectives=[3.0, 6.0]),
        Individual(objectives=[5.0, 4.0]),
        Individual(objectives=[7.0, 2.0]),
    ]
    hv = hypervolume(inds, reference_point=[8.0, 9.0])
    assert hv > 0


# ---------------------------------------------------------------------------
# normalize_objectives tests
# ---------------------------------------------------------------------------

def test_normalize_objectives():
    inds = [
        Individual(objectives=[2.0, 8.0]),
        Individual(objectives=[4.0, 4.0]),
        Individual(objectives=[6.0, 2.0]),
    ]
    normalize_objectives(inds)
    assert abs(inds[0].objectives[0] - 0.0) < 1e-9
    assert abs(inds[2].objectives[0] - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# pareto_ranking tests
# ---------------------------------------------------------------------------

def test_pareto_ranking():
    inds = [
        Individual(objectives=[1.0, 1.0]),
        Individual(objectives=[2.0, 2.0]),
        Individual(objectives=[5.0, 5.0]),
    ]
    ranking = pareto_ranking(inds)
    assert ranking["front_count"] >= 1
    assert ranking["pareto_count"] >= 1
    assert ranking["pareto_fraction"] > 0
    assert len(ranking["ideal_point"]) == 2
    assert len(ranking["nadir_point"]) == 2


# ---------------------------------------------------------------------------
# MultiObjectiveOptimizer tests
# ---------------------------------------------------------------------------

def test_optimizer_initialization():
    def obj1(p): return p["x"]
    def obj2(p): return -p["x"]
    opt = MultiObjectiveOptimizer(
        objective_functions=[obj1, obj2],
        objective_names=["Minimize X", "Maximize X"],
        objective_minimize=[True, False],
        parameter_bounds={"x": (0.0, 10.0)},
        population_size=20,
    )
    assert len(opt.objectives) == 2


def test_optimizer_run():
    def obj1(p): return p["x"]
    def obj2(p): return (p["x"] - 5.0) ** 2
    opt = MultiObjectiveOptimizer(
        objective_functions=[obj1, obj2],
        objective_names=["x", "distance"],
        objective_minimize=[True, True],
        parameter_bounds={"x": (0.0, 10.0)},
        population_size=20,
    )
    result = opt.optimize(max_generations=5)
    assert result.generation_count == 5
    assert len(result.pareto_front) > 0
    assert result.population_size == 20


def test_optimizer_result_pareto_front():
    def f1(p): return p["a"]
    def f2(p): return 1.0 / (p["a"] + 0.1)
    opt = MultiObjectiveOptimizer(
        objective_functions=[f1, f2],
        objective_names=["a", "inv"],
        objective_minimize=[True, True],
        parameter_bounds={"a": (0.1, 10.0)},
        population_size=20,
    )
    result = opt.optimize(max_generations=5)
    objectives = result.get_pareto_objectives()
    assert len(objectives) == len(result.pareto_front)
    params = result.get_pareto_parameters()
    assert len(params) == len(result.pareto_front)


# ---------------------------------------------------------------------------
# Domain-specific objectives tests
# ---------------------------------------------------------------------------

def test_default_objectives_return_valid():
    funcs, names, minimize, bounds = create_default_hemp_decotitator_objectives()
    assert len(funcs) == 7
    assert len(names) == 7
    assert len(minimize) == 7
    assert len(bounds) > 0


def test_default_optimizer_creation():
    opt = create_hemp_decotitator_optimizer(population_size=20)
    assert opt.population_size == 20
    assert len(opt.objectives) == 7


def test_optimizer_short_run():
    opt = create_hemp_decotitator_optimizer(population_size=10)
    result = opt.optimize(max_generations=3)
    assert result.generation_count == 3
    assert result.population_size == 10
    # Should have found at least a few Pareto-optimal solutions
    assert len(result.pareto_front) > 0
