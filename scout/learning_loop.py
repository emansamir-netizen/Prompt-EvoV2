#!/usr/bin/env python3
"""
Learning Loop
Monitors inquiry outcomes and promotes successful dynamic goals 
back into the static pool for long-term knowledge accumulation.
"""

import json
import logging
import os
import shutil
from datetime import datetime
from typing import List, Dict

try:
    from config_loader import get_config
except ImportError:
    print("[ERROR] config_loader not found")
    import sys
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LearningLoop:
    """
    Implements the self-improving feedback loop of the SEED framework.
    """
    
    def __init__(self, static_goals_file: str = "static_goals.json"):
        self.config = get_config()
        self.static_goals_file = static_goals_file
        self.promotion_threshold = self.config.get("analysis", {}).get("learning", {}).get("promotion_threshold", 0.75)
        self.output_file = self.config.get("output", {}).get("promoted_goals", "promoted_goals.json")

    def analyze_results_and_promote(self, mcts_results_file: str, goal_pool_file: str):
        """
        Identify successful dynamic goals and promote them.
        """
        print(f"\n🔄 Running Learning Loop (Threshold: {self.promotion_threshold})")
        
        # Load files
        try:
            with open(mcts_results_file, 'r', encoding='utf-8') as f:
                results = json.load(f).get('best_seeds', [])
            
            with open(goal_pool_file, 'r', encoding='utf-8') as f:
                pool_data = json.load(f)
                goal_pool = pool_data.get('goals', [])
        except Exception as e:
            logger.error(f"Failed to load results for learning loop: {e}")
            return False

        # Map goal_id to goal data
        goal_map = {g['id']: g for g in goal_pool}
        
        # Identify successful dynamic goals
        promoted_goals = []
        already_promoted = set()
        
        for seed in results:
            score = seed.get('revelation_score', 0.0)
            goal_id = seed.get('goal_id')
            
            if score >= self.promotion_threshold:
                goal_data = goal_map.get(goal_id)
                if goal_data and goal_data.get('is_dynamic') and goal_id not in already_promoted:
                    logger.info(f"🏆 Promoting dynamic goal: {goal_data['goal']} (Score: {score:.3f})")
                    print(f"   🏆 Promotion: {goal_data['goal']} (Score: {score:.3f})")
                    promoted_goals.append(goal_data)
                    already_promoted.add(goal_id)

        if not promoted_goals:
            print("   ⏭️  No new goals qualified for promotion.")
            return False

        # Save promoted goals for audit
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "promoted_count": len(promoted_goals),
                "goals": promoted_goals
            }, f, indent=2)

        # Update static_goals.json
        self._update_static_pool(promoted_goals)
        return True

    def _update_static_pool(self, new_goals: List[Dict]):
        """
        Append new goals to the static goals file.
        """
        if not os.path.exists(self.static_goals_file):
            logger.warning(f"Static goals file {self.static_goals_file} not found. Creating new.")
            static_pool = []
        else:
            # Backup
            backup_file = f"{self.static_goals_file}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(self.static_goals_file, backup_file)
            logger.info(f"Backup created: {backup_file}")
            
            with open(self.static_goals_file, 'r', encoding='utf-8') as f:
                try:
                    static_pool = json.load(f)
                except json.JSONDecodeError:
                    static_pool = []

        # Add new goals
        for goal in new_goals:
            # Clean dynamic markers
            promoted = goal.copy()
            promoted['is_dynamic'] = False
            promoted['id'] = f"PROM_{promoted['id']}"
            promoted['_comment'] = f"Promoted from dynamic discovery on {datetime.now().date()}"
            
            # Check for duplicates
            if not any(g.get('goal') == promoted['goal'] for g in static_pool):
                static_pool.append(promoted)

        with open(self.static_goals_file, 'w', encoding='utf-8') as f:
            json.dump(static_pool, f, indent=2, ensure_ascii=False)
        
        print(f"   ✅ Successfully added {len(new_goals)} goals to {self.static_goals_file}")

if __name__ == "__main__":
    # Test
    loop = LearningLoop()
    # loop.analyze_results_and_promote("mcts_best_seeds.json", "goal_pool.json")
