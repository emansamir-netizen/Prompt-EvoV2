#!/usr/bin/env python3
"""
Master Orchestrator
Runs the complete revelation inquiry pipeline:
1. Domain Detection (already exists)
2. Profiler (already exists)
3. Goal Generation (new)
4. Social Engineering (new)
5. MCTS Seed Selection (new)
6. Mutator (to be integrated)
"""

import sys
import logging
import argparse
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def run_pipeline(
    skip_domain: bool = False,
    skip_profiler: bool = False,
    skip_goals: bool = False,
    skip_social: bool = False,
    skip_mcts_select: bool = False,
    skip_mutation: bool = False,
    skip_mcts_learning: bool = False,
    skip_learning_loop: bool = False,
    domain_results: str = "domain_results.json",
    profile_results: str = "profile_report.json",
    static_goals: str = "static_goals.json",
    goal_pool: str = "goal_pool.json",
    seed_candidates: str = "seed_candidates.json",
    selected_seeds: str = "selected_seeds.json",
    mutated_seeds: str = "mutated_seeds.json",
    mcts_output: str = "mcts_best_seeds.json"
):
    """
    Run the complete adaptive revelation pipeline (Authoritative 8-Phase Flow).
    """
    
    print("=" * 80)
    print(" " * 20 + "🚀 ADAPTIVE REVELATION PIPELINE 🚀")
    print(" " * 22 + "(Profile-Driven & Evolutionary)")
    print("=" * 80)
    
    # ========== PHASE 1: Domain Detection ==========
    if not skip_domain:
        print("\nPHASE 1: DOMAIN DETECTION")
        from domain_detection_agent import DomainDetectionAgent
        agent = DomainDetectionAgent()
        results = agent.run()
        domain_results = agent.save_results(results)
    
    # ========== PHASE 2: Profiler ==========
    if not skip_profiler:
        print("\nPHASE 2: VULNERABILITY PROFILING")
        from profiler_agent import ProfilerAgentUltraEnhanced
        agent = ProfilerAgentUltraEnhanced(override_input=domain_results)
        agent.run()
    
    # ========== PHASE 3: Goal Generation (Discovery) ==========
    if not skip_goals:
        print("\nPHASE 3: PROFILE-DRIVEN GOAL DISCOVERY")
        from goal_generator import ProfileDrivenGoalGenerator
        generator = ProfileDrivenGoalGenerator(domain_results, profile_results)
        goals = generator.generate_goals()
        goal_pool = generator.save_goals(goal_pool)
    
    # ========== PHASE 4: Social Engineering ==========
    if not skip_social:
        print("\nPHASE 4: SOCIAL ENGINEERING SCENARIOS")
        from social_engineering_agent import SocialEngineeringAgent
        agent = SocialEngineeringAgent(goal_pool)
        seeds = agent.generate_seeds(seeds_per_goal=2)
        seed_candidates = agent.save_seeds(seed_candidates)
    
    # ========== PHASE 5: MCTS Selection (Cold Start) ==========
    if not skip_mcts_select:
        print("\nPHASE 5: MCTS STRUCTURAL SELECTION (COLD START)")
        from mcts_seed_selector import MCTSExplore
        selector = MCTSExplore(seed_candidates, profile_results)
        best_struct = selector.select_seeds_structurally(num_seeds=10)
        
        # Save for mutator
        with open(selected_seeds, 'w', encoding='utf-8') as f:
            json.dump({"seeds": best_struct}, f, indent=2)
        print(f"✅ Selected {len(best_struct)} seeds for mutation (Score: 0, Structural bias only)")

    # ========== PHASE 6: Mutation (Evolution) ==========
    if not skip_mutation:
        print("\nPHASE 6: INQUIRY EVOLUTION (MUTATION)")
        from mutator_agent import MutatorAgent
        with open(selected_seeds, 'r', encoding='utf-8') as f:
            seeds_to_mutate = json.load(f).get('seeds', [])
        
        mutator = MutatorAgent()
        mutations = mutator.mutate_pool(seeds_to_mutate, num_variations=3)
        mutated_seeds = mutator.save_mutations(mutations, mutated_seeds)
        print(f"✅ Generated {len(mutations)} mutated inquiry seeds")

    # ========== PHASE 7: MCTS Learning (Real-World Testing) ==========
    if not skip_mcts_learning:
        print("\nPHASE 7: MCTS LEARNING (REAL-WORLD EVALUATION)")
        from mcts_seed_selector import MCTSExplore
        # We initialize MCTS with mutated seeds
        selector = MCTSExplore(mutated_seeds, profile_results)
        # Run iterations with real evaluation
        best_final = selector.run_mcts(num_best_seeds=10)
        mcts_output = selector.save_results(mcts_output)
        print(f"✅ MCTS Learning Phase Complete: {len(best_final)} results evaluated")

    # ========== PHASE 8: Learning Loop (Knowledge Promotion) ==========
    if not skip_learning_loop:
        print("\nPHASE 8: KNOWLEDGE PROMOTION (LEARNING LOOP)")
        from learning_loop import LearningLoop
        loop = LearningLoop(static_goals_file=static_goals)
        loop.analyze_results_and_promote(mcts_output, goal_pool)
    
    print("\n" + "=" * 80)
    print("🎉 ADAPTIVE PIPELINE RUN COMPLETE!")
    print("=" * 80)
    return True

def main():
    parser = argparse.ArgumentParser(description="Master Orchestrator - Adaptive SEED Pipeline")
    parser.add_argument("--skip-domain", action="store_true")
    parser.add_argument("--skip-profiler", action="store_true")
    parser.add_argument("--skip-goals", action="store_true")
    parser.add_argument("--skip-social", action="store_true")
    parser.add_argument("--skip-select", action="store_true")
    parser.add_argument("--skip-mutation", action="store_true")
    parser.add_argument("--skip-testing", action="store_true")
    parser.add_argument("--skip-learning", action="store_true")
    
    args = parser.parse_args()
    
    try:
        run_pipeline(
            skip_domain=args.skip_domain,
            skip_profiler=args.skip_profiler,
            skip_goals=args.skip_goals,
            skip_social=args.skip_social,
            skip_mcts_select=args.skip_select,
            skip_mutation=args.skip_mutation,
            skip_mcts_learning=args.skip_testing,
            skip_learning_loop=args.skip_learning
        )
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
