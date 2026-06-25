#!/usr/bin/env python3
"""
Master Orchestrator - CORRECTED VERSION
Runs the complete revelation inquiry pipeline with proper state awareness.

CRITICAL FIXES:
1. State-aware execution (no blind proceeding)
2. Proper validation between phases
3. Cold-start MCTS support (Phase 5)
4. Real evaluation MCTS (Phase 7 - not yet implemented)
5. No assumptions about data availability
"""

import sys
import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class StateAwarePipeline:
    """
    State-aware pipeline that validates data availability before proceeding.
    """
    
    def __init__(self):
        self.state = {
            "domain_detected": False,
            "profile_created": False,
            "goals_generated": False,
            "seeds_generated": False,
            "seeds_selected": False
        }
        
        self.outputs = {}
    
    def _validate_file_exists(self, filepath: str, description: str) -> bool:
        """Check if a file exists and contains valid data"""
        if not Path(filepath).exists():
            logger.error(f"{description} not found: {filepath}")
            return False
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not data:
                logger.error(f"{description} is empty: {filepath}")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error loading {description}: {e}")
            return False
    
    def _validate_domain_results(self, filepath: str) -> bool:
        """Validate domain detection results"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Check for required structure
            if 'embedding_analysis' not in data:
                logger.error("domain_results missing 'embedding_analysis'")
                return False
            
            emb = data['embedding_analysis']
            if 'primary_domain' not in emb:
                logger.error("embedding_analysis missing 'primary_domain'")
                return False
            
            # Check for responses (should have at least some data)
            responses = data.get('all_responses', [])
            if len(responses) == 0:
                logger.warning("No responses in domain_results (may affect profiling)")
                # Don't fail - profiler can handle this
            
            return True
        except Exception as e:
            logger.error(f"Domain validation error: {e}")
            return False
    
    def _validate_profile_results(self, filepath: str) -> bool:
        """Validate vulnerability profile"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            required = ['vulnerability_scores', 'primary_weakness']
            for key in required:
                if key not in data:
                    logger.error(f"profile_report missing '{key}'")
                    return False
            
            # Check that vulnerability_scores is not empty
            if not data['vulnerability_scores']:
                logger.error("vulnerability_scores is empty")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Profile validation error: {e}")
            return False
    
    def run_phase_1_domain_detection(self) -> str:
        """Phase 1: Domain Detection"""
        print("\n" + "=" * 70)
        print("PHASE 1: DOMAIN DETECTION")
        print("=" * 70)
        
        from domain_detection_agent import DomainDetectionAgent
        
        try:
            agent = DomainDetectionAgent()
            results = agent.run()
            output_file = agent.save_results(results)
            
            # Validate results
            if not self._validate_domain_results(output_file):
                raise ValueError("Invalid domain detection output")
            
            self.state["domain_detected"] = True
            self.outputs["domain_file"] = output_file
            
            print(f"✅ Phase 1 Complete: {output_file}")
            return output_file
            
        except Exception as e:
            logger.error(f"Phase 1 failed: {e}")
            print(f"\n❌ Phase 1 FAILED: {e}")
            raise
    
    def run_phase_2_profiling(self, domain_file: str) -> str:
        """Phase 2: Vulnerability Profiling"""
        print("\n" + "=" * 70)
        print("PHASE 2: VULNERABILITY PROFILING")
        print("=" * 70)
        
        # Validate input
        if not self._validate_domain_results(domain_file):
            raise ValueError(f"Invalid domain_file: {domain_file}")
        
        from profiler_agent import ProfilerAgentUltraEnhanced
        
        try:
            agent = ProfilerAgentUltraEnhanced(override_input=domain_file)
            agent.run()
            
            output_file = agent.config.output_settings.get(
                'profile_report',
                'profile_report.json'
            )
            
            # Validate results
            if not self._validate_profile_results(output_file):
                raise ValueError("Invalid profile output")
            
            self.state["profile_created"] = True
            self.outputs["profile_file"] = output_file
            
            print(f"✅ Phase 2 Complete: {output_file}")
            return output_file
            
        except Exception as e:
            logger.error(f"Phase 2 failed: {e}")
            print(f"\n❌ Phase 2 FAILED: {e}")
            raise
    
    def run_phase_3_goal_generation(
        self,
        domain_file: str,
        profile_file: str,
        use_dynamic: bool = True
    ) -> str:
        """Phase 3: Goal Generation (Static + Dynamic Discovery)"""
        print("\n" + "=" * 70)
        print("PHASE 3: GOAL GENERATION")
        print("=" * 70)
        
        # Validate inputs
        if not self._validate_domain_results(domain_file):
            raise ValueError(f"Invalid domain_file: {domain_file}")
        if not self._validate_profile_results(profile_file):
            raise ValueError(f"Invalid profile_file: {profile_file}")
        
        # Import corrected generator
        try:
            from goal_generator_corrected import ProfileDrivenGoalGenerator
        except ImportError:
            logger.warning("Corrected generator not found, trying original")
            from goal_generator import ProfileDrivenGoalGenerator
        
        try:
            generator = ProfileDrivenGoalGenerator(
                domain_file=domain_file,
                profile_file=profile_file
            )
            
            goals = generator.generate_goals(use_dynamic=use_dynamic)
            output_file = generator.save_goals("goal_pool.json")
            
            # Validate output
            with open(output_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not data.get('goals') or len(data['goals']) == 0:
                logger.error("No goals generated!")
                raise ValueError("Goal generation produced no goals")
            
            self.state["goals_generated"] = True
            self.outputs["goals_file"] = output_file
            
            print(f"✅ Phase 3 Complete: {len(goals)} goals in {output_file}")
            return output_file
            
        except Exception as e:
            logger.error(f"Phase 3 failed: {e}")
            print(f"\n❌ Phase 3 FAILED: {e}")
            raise
    
    def run_phase_4_social_engineering(self, goals_file: str) -> str:
        """Phase 4: Social Engineering Seed Generation"""
        print("\n" + "=" * 70)
        print("PHASE 4: SOCIAL ENGINEERING")
        print("=" * 70)
        
        # Validate input
        if not self._validate_file_exists(goals_file, "Goals file"):
            raise ValueError(f"Invalid goals_file: {goals_file}")
        
        from social_engineering_agent import SocialEngineeringAgent
        
        try:
            agent = SocialEngineeringAgent(goals_file)
            seeds = agent.generate_seeds(seeds_per_goal=2)
            output_file = agent.save_seeds("seed_candidates.json")
            
            # Validate output
            with open(output_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not data.get('seeds') or len(data['seeds']) == 0:
                logger.error("No seeds generated!")
                raise ValueError("Social engineering produced no seeds")
            
            self.state["seeds_generated"] = True
            self.outputs["seeds_file"] = output_file
            
            print(f"✅ Phase 4 Complete: {len(seeds)} seeds in {output_file}")
            return output_file
            
        except Exception as e:
            logger.error(f"Phase 4 failed: {e}")
            print(f"\n❌ Phase 4 FAILED: {e}")
            raise
    
    def run_phase_5_mcts_cold_start(
        self,
        seeds_file: str,
        profile_file: str,
        num_seeds: int = 10
    ) -> str:
        """
        Phase 5: MCTS Cold-Start Selection
        
        Uses structural selection ONLY (no real evaluation).
        This is the stopping point before mutation.
        """
        print("\n" + "=" * 70)
        print("PHASE 5: MCTS COLD-START SELECTION")
        print("=" * 70)
        print("⚠️  This phase uses STRUCTURAL selection only (no real inquiries)")
        print("   Revelation scores = 0 (intentional - no evaluation yet)")
        
        # Validate inputs
        if not self._validate_file_exists(seeds_file, "Seeds file"):
            raise ValueError(f"Invalid seeds_file: {seeds_file}")
        if not self._validate_profile_results(profile_file):
            raise ValueError(f"Invalid profile_file: {profile_file}")
        
        # Import corrected MCTS
        try:
            from mcts_seed_selector_corrected import MCTSExplore
        except ImportError:
            logger.warning("Corrected MCTS not found, trying original")
            from mcts_seed_selector import MCTSExplore
        
        try:
            selector = MCTSExplore(seeds_file, profile_file)
            
            # Use cold-start mode
            best_seeds = selector.select_seeds_structurally(num_seeds=num_seeds)
            
            # Save for next phase (mutator)
            output_file = "selected_seeds.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump({"seeds": best_seeds}, f, indent=2)
            
            self.state["seeds_selected"] = True
            self.outputs["selected_seeds_file"] = output_file
            
            print(f"\n✅ Phase 5 Complete:")
            print(f"   Selected {len(best_seeds)} seeds (structural selection)")
            print(f"   Saved to: {output_file}")
            print(f"\n🛑 PIPELINE STOPS HERE (as specified)")
            print(f"   Next phases (mutation, real evaluation) not yet implemented")
            
            return output_file
            
        except Exception as e:
            logger.error(f"Phase 5 failed: {e}")
            print(f"\n❌ Phase 5 FAILED: {e}")
            raise
    
    def run_all(
        self,
        skip_domain: bool = False,
        skip_profile: bool = False,
        skip_goals: bool = False,
        skip_social: bool = False,
        skip_mcts: bool = False,
        use_dynamic_goals: bool = True
    ):
        """Run the complete pipeline up to MCTS cold-start"""
        
        print("=" * 80)
        print(" " * 20 + "🚀 SEED FRAMEWORK PIPELINE 🚀")
        print(" " * 15 + "(Corrected & State-Aware Version)")
        print("=" * 80)
        
        try:
            # Phase 1: Domain Detection
            if not skip_domain:
                domain_file = self.run_phase_1_domain_detection()
            else:
                domain_file = "domain_results.json"
                if not self._validate_domain_results(domain_file):
                    raise ValueError("Skipped domain detection but file is invalid")
                print(f"\n⏭️  Skipped Phase 1, using: {domain_file}")
            
            # Phase 2: Profiling
            if not skip_profile:
                profile_file = self.run_phase_2_profiling(domain_file)
            else:
                profile_file = "profile_report.json"
                if not self._validate_profile_results(profile_file):
                    raise ValueError("Skipped profiling but file is invalid")
                print(f"\n⏭️  Skipped Phase 2, using: {profile_file}")
            
            # Phase 3: Goal Generation
            if not skip_goals:
                goals_file = self.run_phase_3_goal_generation(
                    domain_file,
                    profile_file,
                    use_dynamic_goals
                )
            else:
                goals_file = "goal_pool.json"
                if not self._validate_file_exists(goals_file, "Goals file"):
                    raise ValueError("Skipped goal generation but file is invalid")
                print(f"\n⏭️  Skipped Phase 3, using: {goals_file}")
            
            # Phase 4: Social Engineering
            if not skip_social:
                seeds_file = self.run_phase_4_social_engineering(goals_file)
            else:
                seeds_file = "seed_candidates.json"
                if not self._validate_file_exists(seeds_file, "Seeds file"):
                    raise ValueError("Skipped social engineering but file is invalid")
                print(f"\n⏭️  Skipped Phase 4, using: {seeds_file}")
            
            # Phase 5: MCTS Cold-Start
            if not skip_mcts:
                selected_file = self.run_phase_5_mcts_cold_start(
                    seeds_file,
                    profile_file,
                    num_seeds=10
                )
            else:
                print(f"\n⏭️  Skipped Phase 5 (MCTS selection)")
            
            # Final summary
            print("\n" + "=" * 80)
            print("✅ PIPELINE EXECUTION COMPLETE!")
            print("=" * 80)
            
            print(f"\n📁 Generated Files:")
            for key, filepath in self.outputs.items():
                print(f"   {key:20s}: {filepath}")
            
            print(f"\n🛑 Stopped at: Social Engineering + MCTS Cold-Start Selection")
            print(f"   (As specified - no mutation or real evaluation yet)")
            
            print("\n" + "=" * 80)
            
            return self.outputs
            
        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            print(f"\n❌ PIPELINE FAILED at current phase")
            print(f"   Error: {e}")
            print(f"\n📊 Pipeline State:")
            for phase, completed in self.state.items():
                status = "✅" if completed else "❌"
                print(f"   {status} {phase}")
            raise


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="SEED Framework Pipeline - Corrected Version"
    )
    parser.add_argument("--skip-domain", action="store_true", help="Skip domain detection")
    parser.add_argument("--skip-profile", action="store_true", help="Skip profiling")
    parser.add_argument("--skip-goals", action="store_true", help="Skip goal generation")
    parser.add_argument("--skip-social", action="store_true", help="Skip social engineering")
    parser.add_argument("--skip-mcts", action="store_true", help="Skip MCTS selection")
    parser.add_argument("--no-dynamic", action="store_true", help="Disable dynamic goal generation")
    
    args = parser.parse_args()
    
    try:
        pipeline = StateAwarePipeline()
        
        pipeline.run_all(
            skip_domain=args.skip_domain,
            skip_profile=args.skip_profile,
            skip_goals=args.skip_goals,
            skip_social=args.skip_social,
            skip_mcts=args.skip_mcts,
            use_dynamic_goals=not args.no_dynamic
        )
        
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()