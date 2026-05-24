#!/usr/bin/env python3
"""
Basic test script to verify the SAT solver interface works.
"""

try:
    from qecc_sat.sat_solver import SATSolver, SolverType, get_available_solvers, create_solver
    print("✓ Successfully imported sat_solver module")
except ImportError as e:
    print(f"✗ Import error: {e}")
    print("Please install python-sat: pip install python-sat")
    exit(1)

# Test 1: Check available solvers
print("\nTest 1: Available solvers")
try:
    solvers = get_available_solvers()
    print(f"✓ Found {len(solvers)} available solvers")
    print(f"  First few: {solvers[:5]}")
except Exception as e:
    print(f"✗ Error: {e}")

# Test 2: Create solver
print("\nTest 2: Create solver")
try:
    solver = SATSolver(solver_type=SolverType.MINISAT22)
    print("✓ Successfully created solver")
    solver.delete()
except Exception as e:
    print(f"✗ Error: {e}")

# Test 3: Simple solve
print("\nTest 3: Simple solve")
try:
    with SATSolver(solver_type=SolverType.MINISAT22) as solver:
        solver.add_clause([-1, 2])
        solver.add_clause([-2, 3])
        result = solver.solve()
        print(f"✓ Solve completed: satisfiable = {result}")
        if result:
            model = solver.get_model()
            print(f"  Model: {model}")
except Exception as e:
    print(f"✗ Error: {e}")

# Test 4: Create by name
print("\nTest 4: Create solver by name")
try:
    solver = create_solver("glucose3")
    solver.add_clause([1, 2])
    result = solver.solve()
    print(f"✓ Created by name and solved: satisfiable = {result}")
    solver.delete()
except Exception as e:
    print(f"✗ Error: {e}")

print("\n" + "="*50)
print("All basic tests completed!")
print("="*50)
