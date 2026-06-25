#!/usr/bin/env python3
"""
Create goal_pool.json from static_goals.json without using API credits.
This bypasses the dynamic goal generation step.
"""

import json
import sys

def create_goal_pool():
    """Create goal pool from static goals only"""
    
    print("=" * 60)
    print("GOAL POOL CREATOR (No API Credits Needed)")
    print("=" * 60)
    
    # Load static goals
    try:
        with open('static_goals.json', 'r', encoding='utf-8') as f:
            static_goals = json.load(f)
        print(f"\n✅ Loaded static_goals.json")
    except FileNotFoundError:
        print("\n❌ ERROR: static_goals.json not found!")
        print("   Make sure you're in the correct directory.")
        return False
    
    # Filter out comments
    all_goals = [g for g in static_goals if not g.get('_comment')]
    print(f"   Found {len(all_goals)} total goals")
    
    # Load domain results to get target domain
    try:
        with open('domain_results.json', 'r', encoding='utf-8') as f:
            domain_data = json.load(f)
        target_domain = domain_data.get('embedding_analysis', {}).get('primary_domain', 'financial_advisor')
        target_model = domain_data.get('model', 'unknown')
    except:
        print("\n⚠️  WARNING: Could not load domain_results.json")
        print("   Using default: financial_advisor")
        target_domain = 'financial_advisor'
        target_model = 'unknown'
    
    print(f"   Target domain: {target_domain}")
    
    # Filter goals for target domain
    domain_goals = [g for g in all_goals if g.get('domain') == target_domain]
    
    if not domain_goals:
        print(f"\n⚠️  WARNING: No goals found for domain '{target_domain}'")
        print(f"   Available domains: {set(g.get('domain') for g in all_goals)}")
        print(f"   Using all goals instead...")
        domain_goals = all_goals
    
    print(f"   Filtered to {len(domain_goals)} goals for {target_domain}")
    
    # Create goal pool structure
    goal_pool = {
        "target_model": target_model,
        "target_domain": target_domain,
        "total_goals": len(domain_goals),
        "static_count": len(domain_goals),
        "dynamic_count": 0,
        "goals": [
            {
                "id": g['id'],
                "domain": g['domain'],
                "weakness": g['weakness'],
                "goal": g['goal'],
                "description": g['description'],
                "is_dynamic": False,
                "parent_id": None
            }
            for g in domain_goals
        ]
    }
    
    # Save goal pool
    with open('goal_pool.json', 'w', encoding='utf-8') as f:
        json.dump(goal_pool, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Created goal_pool.json")
    print(f"\n📊 Summary:")
    print(f"   Total goals: {len(domain_goals)}")
    print(f"   Domain: {target_domain}")
    print(f"   Static goals: {len(domain_goals)}")
    print(f"   Dynamic goals: 0 (skipped to save API credits)")
    
    print(f"\n💡 Next Steps:")
    print(f"   1. Run: python run_pipeline.py --skip-goals")
    print(f"   2. This will use your static goals for social engineering")
    
    print("\n" + "=" * 60)
    
    return True


if __name__ == "__main__":
    try:
        success = create_goal_pool()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
