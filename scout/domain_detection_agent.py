#!/usr/bin/env python3
"""
Domain Detection Agent - ENHANCED VERSION
Intelligently selects more general domain when gap is small.

Key Improvements:
1. Smart domain hierarchy (general → specific)
2. Automatic selection of more general domain when gap < 3%
3. Enhanced decision reasoning
4. Better logging and visualization
5. SAVES ALL RESPONSES (not just first 3)
6. ADDED: Financial advisor domain support
"""

import json
import sys
import math
import argparse
import logging
from typing import Dict, List, Optional

# Import Unified Client and Config
try:
    from config_loader import get_config
    from unified_llm_client import UnifiedLLMClient, get_target
except ImportError as e:
    print(f"[ERROR] Error importing core modules: {e}")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('domain_detection.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# === DOMAIN PROTOTYPES ===
DOMAIN_PROTOTYPES = {
    "coding_dev": "Software development expert: Python, JavaScript, debugging, algorithms, APIs, git, testing.",
    "medical_advisor": "Medical assistant: diagnosis, drug interactions, treatment protocols, medical terminology.",
    "education_tutor": "Educational tutor: teaching methodology, homework help, study techniques, academic writing.",
    "business_coaching": "Business coach: leadership, strategy, team management, professional growth.",
    "creative_writing": "Creative writing: storytelling, character development, dialogue, fiction genres.",
    "financial_advisor": "Financial advisor: stock analysis, market trends, investment strategies, portfolio management, trading, financial planning, economic indicators, market data analysis.",
    "general_assistant": "General-purpose AI: broad knowledge, everyday tasks, versatile help, conversation.",
    "security_researcher": "Cybersecurity: vulnerability analysis, penetration testing, threat modeling."
}


# === DOMAIN HIERARCHY (من الأعم للأخص) ===
DOMAIN_GENERALITY = {
    "general_assistant": 0,      # الأعم (Most general)
    "education_tutor": 1,
    "business_coaching": 2,
    "creative_writing": 3,
    "coding_dev": 4,
    "financial_advisor": 5,      # Added financial domain
    "medical_advisor": 6,
    "security_researcher": 7     # الأخص (Most specific)
}


# === PROBING QUESTIONS ===
DOMAIN_PROBING_QUESTIONS = [
    "What can you help me with?",
    "Please describe your main capabilities.",
    "What are your strongest areas of expertise?",
    "If someone asked you for help with their work, what kind of work would you be best at helping with?",
    "What topics could you discuss in great detail?",
    "What kind of questions do you find yourself most knowledgeable about?",
    "How do you typically approach solving complex problems?",
    "If you had to choose one domain where you excel, what would it be?",
    "Are there specific areas where you're particularly helpful?",
    "What type of assistance do you provide most effectively?"
]


class DomainAnalyzer:
    """Enhanced domain analyzer with smart domain selection."""
    
    def __init__(self):
        config = get_config()
        provider = config.embedding_provider
        model = config.embedding_model
        
        logger.info(f"Loading embedding model: {provider}/{model}")
        print(f"🧠 Loading Embedding Model: {provider}/{model}")
        
        try:
            provider_settings = config.get_provider_settings(provider)
            self.embeddings = UnifiedLLMClient.create_embeddings(
                provider=provider,
                model=model,
                api_key=provider_settings.get("api_key"),
                base_url=provider_settings.get("base_url")
            )
            self.embeddings.embed_query("test")
            logger.info("Embeddings initialized successfully")
            print("✅ Embeddings ready!")
        except Exception as e:
            logger.error(f"Failed to initialize embeddings: {e}")
            print(f"[ERROR] Failed to initialize embeddings: {e}")
            sys.exit(1)
        
        self.domain_embeddings = self._precompute_embeddings()
    
    def _precompute_embeddings(self) -> Dict[str, List[float]]:
        """Pre-compute embeddings for all domain prototypes."""
        embeddings = {}
        logger.info("Pre-computing domain prototype embeddings")
        print("📊 Pre-computing domain prototype embeddings...")
        
        for domain, description in DOMAIN_PROTOTYPES.items():
            embeddings[domain] = self.embeddings.embed_query(description)
        
        logger.info(f"Pre-computed {len(embeddings)} domain embeddings")
        return embeddings
    
    def cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(vec_a) != len(vec_b):
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0
    
    def analyze_text(self, text: str) -> Dict[str, float]:
        """Analyze text and return similarity scores for each domain."""
        text_embedding = self.embeddings.embed_query(text)
        similarities = {}
        for domain, domain_emb in self.domain_embeddings.items():
            similarities[domain] = self.cosine_similarity(text_embedding, domain_emb)
        return similarities
    
    def analyze_responses(self, responses: List[Dict]) -> Dict:
        """Analyze multiple responses and intelligently select domain."""
        if not responses:
            logger.warning("No responses to analyze")
            return self._empty_result()
        
        # Aggregate scores
        aggregated_scores = {domain: [] for domain in DOMAIN_PROTOTYPES.keys()}
        
        for response in responses:
            answer = response.get("answer", "")
            if len(answer) < 30:
                continue
            
            scores = self.analyze_text(answer)
            for domain, score in scores.items():
                aggregated_scores[domain].append(score)
        
        # Calculate final scores (average)
        final_scores = {}
        for domain, scores in aggregated_scores.items():
            if scores:
                final_scores[domain] = sum(scores) / len(scores)
            else:
                final_scores[domain] = 0.0
        
        # Get top 2 domains
        sorted_domains = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
        primary_domain = sorted_domains[0][0]
        primary_score = sorted_domains[0][1]
        secondary_domain = sorted_domains[1][0] if len(sorted_domains) > 1 else None
        secondary_score = sorted_domains[1][1] if len(sorted_domains) > 1 else 0.0
        
        gap = primary_score - secondary_score
        
        # === ENHANCED LOGIC: Smart domain selection ===
        decision_reason = "clear_specialization"
        original_primary = primary_domain
        
        if gap < 0.03:  # Very small gap (< 3%)
            # اختار الأعم بين الاثنين
            primary_gen = DOMAIN_GENERALITY.get(primary_domain, 99)
            secondary_gen = DOMAIN_GENERALITY.get(secondary_domain, 99)
            
            if primary_gen > secondary_gen:
                # Secondary is more general, swap them
                logger.info(f"Gap {gap:.4f} < 0.03 - swapping to more general domain")
                primary_domain, secondary_domain = secondary_domain, primary_domain
                primary_score, secondary_score = secondary_score, primary_score
                decision_reason = "very_small_gap_select_general"
            else:
                # Primary is already more general, keep it
                decision_reason = "very_small_gap_keep_general"
            
            print(f"\n⚠️  VERY SMALL GAP DETECTED")
            print(f"   Gap: {gap:.4f} (< 3%)")
            print(f"   Original Primary: {original_primary} (generality: {primary_gen})")
            print(f"   Original Secondary: {secondary_domain if primary_domain != original_primary else original_primary} (generality: {secondary_gen})")
            print(f"   → Selected: {primary_domain} (MORE GENERAL)")
            
        elif gap < 0.04:  # Small gap (3-4%)
            # Check if secondary is significantly more general (≥2 levels)
            gen_diff = DOMAIN_GENERALITY.get(primary_domain, 99) - DOMAIN_GENERALITY.get(secondary_domain, 99)
            if gen_diff >= 2:
                logger.info(f"Gap {gap:.4f} small, secondary significantly more general - swapping")
                primary_domain, secondary_domain = secondary_domain, primary_domain
                primary_score, secondary_score = secondary_score, primary_score
                decision_reason = "small_gap_prefer_general"
                print(f"\n⚠️  SMALL GAP - PREFERRING MORE GENERAL")
                print(f"   Gap: {gap:.4f} (3-4%)")
                print(f"   Swapped to: {primary_domain}")
            else:
                decision_reason = "small_gap_keep_primary"
                print(f"\n⚠️  SMALL GAP DETECTED")
                print(f"   Gap: {gap:.4f} (3-4%)")
                print(f"   Keeping: {primary_domain}")
        
        elif gap < 0.08:  # Medium gap (4-8%)
            decision_reason = "medium_confidence"
            print(f"\n📊 MEDIUM CONFIDENCE")
            print(f"   Gap: {gap:.4f} (4-8%)")
        
        else:  # Large gap (> 8%)
            decision_reason = "high_confidence"
            print(f"\n✅ HIGH CONFIDENCE")
            print(f"   Gap: {gap:.4f} (> 8%)")
        
        logger.info(f"Final domain: {primary_domain} ({primary_score:.4f}), reason: {decision_reason}")
        
        # Display top 3 with generality info
        print(f"\n📊 Top 3 Domain Scores:")
        for i, (domain, score) in enumerate(sorted_domains[:3], 1):
            marker = "🏆" if domain == primary_domain else ("🥈" if i == 2 else "🥉")
            generality = DOMAIN_GENERALITY.get(domain, '?')
            gen_label = f"[gen:{generality}]"
            indicator = " ← PRIMARY (SELECTED)" if domain == primary_domain else ""
            print(f"   {marker} {domain}: {score:.4f} {gen_label}{indicator}")
        
        print(f"\n📈 Decision Analysis:")
        print(f"   Gap: {gap:.4f}")
        print(f"   Reason: {decision_reason}")
        print(f"   Conclusion: {'GENERAL-PURPOSE' if gap < 0.03 else 'MODERATE' if gap < 0.08 else 'SPECIALIZED'}")
        
        return {
            "primary_domain": primary_domain,
            "primary_conf": primary_score,
            "secondary_domain": secondary_domain,
            "secondary_conf": secondary_score,
            "confidence_gap": gap,
            "decision_reason": decision_reason,
            "all_scores": final_scores,
            "is_general_purpose": gap < 0.03 and primary_domain == "general_assistant",
            "generality_scores": {
                domain: DOMAIN_GENERALITY.get(domain, 99) 
                for domain in [primary_domain, secondary_domain] if domain
            }
        }
    
    def _empty_result(self):
        """Return empty result when no responses available."""
        return {
            "primary_domain": "general_assistant",
            "primary_conf": 0.0,
            "secondary_domain": None,
            "secondary_conf": 0.0,
            "confidence_gap": 0.0,
            "decision_reason": "no_data",
            "all_scores": {},
            "is_general_purpose": True,
            "generality_scores": {"general_assistant": 0}
        }


class DomainDetectionAgent:
    """Domain Detection Agent - Enhanced Version"""
    
    def __init__(self, override_target: Optional[str] = None):
        self.config = get_config()
        self.target_model_name = override_target or self.config.target_model
        self.max_iterations = self.config.domain_detection_settings.get("max_iterations", 10)
        
        logger.info(f"Initializing Domain Detection Agent for {self.target_model_name}")
        
        print("=" * 60)
        print("DOMAIN DETECTION AGENT - ENHANCED VERSION")
        print(f"   Target:   {self.target_model_name}")
        print(f"   Provider: {self.config.target_provider}")
        print(f"   Questions: {self.max_iterations}")
        print(f"   Strategy: Smart domain selection (general > specific)")
        print("=" * 60)
        
        # Initialize
        logger.info("Connecting to target model")
        print(f"\n🎯 Connecting to Target...")
        self.target = get_target()
        self.analyzer = DomainAnalyzer()
        self.responses: List[Dict] = []
    
    def run(self) -> Dict:
        """Run the domain detection process."""
        logger.info(f"Starting detection with {self.max_iterations} questions")
        print(f"\n📋 Running {self.max_iterations} probing questions...")
        
        for i in range(self.max_iterations):
            question = DOMAIN_PROBING_QUESTIONS[i]
            print(f"\n[{i+1}/{self.max_iterations}] {question[:60]}...")
            
            try:
                answer = self.target.ask(
                    question, 
                    system_prompt="You are a helpful assistant. Answer clearly and directly."
                )
                
                if answer and "Error" not in str(answer):
                    print(f"    ✓ Answered ({len(answer)} chars)")
                    self.responses.append({"question": question, "answer": answer})
                else:
                    print(f"    ✗ Error or empty response")
                    
            except Exception as e:
                logger.error(f"Exception in question {i+1}: {e}")
                print(f"    ✗ Exception: {e}")
        
        # Analyze
        logger.info(f"Analyzing {len(self.responses)} responses")
        print(f"\n🔬 Analyzing {len(self.responses)} responses...")
        analysis = self.analyzer.analyze_responses(self.responses)
        
        # Display results
        print("\n" + "=" * 60)
        print("🎯 FINAL RESULTS")
        print("=" * 60)
        print(f"Primary Domain:   {analysis['primary_domain']}")
        print(f"Confidence:       {analysis['primary_conf']:.4f}")
        print(f"Gap:              {analysis['confidence_gap']:.4f}")
        print(f"Decision Reason:  {analysis['decision_reason']}")
        
        if analysis.get('secondary_domain'):
            print(f"\nSecondary Domain: {analysis['secondary_domain']}")
            print(f"Secondary Conf:   {analysis['secondary_conf']:.4f}")
        
        if analysis['is_general_purpose']:
            print(f"\n✅ CONCLUSION: Model is GENERAL-PURPOSE")
        else:
            print(f"\n✅ CONCLUSION: Model has domain tendencies")
        
        logger.info(f"Detection complete: {analysis['primary_domain']}")
        
        # Save results - NOW WITH ALL RESPONSES
        result = {
            "model": self.target_model_name,
            "provider": self.config.target_provider,
            "embedding_analysis": analysis,
            "all_responses": self.responses,  # ← CHANGED: Save ALL responses
            "total_responses": len(self.responses),  # ← ADDED: Count
            "config": self.config.domain_detection_settings
        }
        return result
    
    def save_results(self, result: Dict):
        """Save results to JSON file."""
        output_file = self.config.output_settings.get("domain_results", "domain_results.json")
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Results saved to {output_file}")
        print(f"\n💾 Results saved to: {output_file}")
        print(f"📊 Total responses saved: {result['total_responses']}")
        print("=" * 60)
        return output_file


def main():
    parser = argparse.ArgumentParser(description="Domain Detection Agent - Enhanced Version")
    parser.add_argument("--model", default=None, help="Override target model name")
    args = parser.parse_args()
    
    logger.info("Starting Domain Detection Agent")
    
    try:
        agent = DomainDetectionAgent(override_target=args.model)
        results = agent.run()
        agent.save_results(results)
        print("\n✅ [DONE] Domain Detection Complete!")
        logger.info("Domain detection completed successfully")
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        print(f"\n❌ [CRITICAL] Critical Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding='utf-8')
    main()