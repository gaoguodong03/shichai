#!/usr/bin/env python3
"""
Prompt Optimization Script

Automatically test and optimize prompts using A/B testing and metrics tracking.
"""

import json
import time
from typing import List, Dict, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import numpy as np


@dataclass
class TestCase:
    input: Dict[str, Any]
    expected_output: str
    metadata: Dict[str, Any] = None


class PromptOptimizer:
    def __init__(self, llm_client, test_suite: List[TestCase]):
        self.client = llm_client
        self.test_suite = test_suite
        self.results_history = []
        self.executor = ThreadPoolExecutor()

    def shutdown(self):
        """Shutdown the thread pool executor."""
        self.executor.shutdown(wait=True)

    def evaluate_prompt(self, prompt_template: str, test_cases: List[TestCase] = None) -> Dict[str, float]:
        """Evaluate a prompt template against test cases in parallel."""
        if test_cases is None:
            test_cases = self.test_suite

        metrics = {
            'accuracy': [],
            'latency': [],
            'token_count': [],
            'success_rate': []
        }

        def process_test_case(test_case):
            start_time = time.time()
            prompt = prompt_template.format(**test_case.input)
            response = self.client.complete(prompt)
            latency = time.time() - start_time
            token_count = len(prompt.split()) + len(response.split())
            success = 1 if response else 0
            accuracy = self.calculate_accuracy(response, test_case.expected_output)
            return {
                'latency': latency,
                'token_count': token_count,
                'success_rate': success,
                'accuracy': accuracy
            }

        results = list(self.executor.map(process_test_case, test_cases))

        for result in results:
            metrics['latency'].append(result['latency'])
            metrics['token_count'].append(result['token_count'])
            metrics['success_rate'].append(result['success_rate'])
            metrics['accuracy'].append(result['accuracy'])

        return {
            'avg_accuracy': np.mean(metrics['accuracy']),
            'avg_latency': np.mean(metrics['latency']),
            'p95_latency': np.percentile(metrics['latency'], 95),
            'avg_tokens': np.mean(metrics['token_count']),
            'success_rate': np.mean(metrics['success_rate'])
        }

    def calculate_accuracy(self, response: str, expected: str) -> float:
        """Calculate accuracy score between response and expected output."""
        if response.strip().lower() == expected.strip().lower():
            return 1.0
        response_words = set(response.lower().split())
        expected_words = set(expected.lower().split())
        if not expected_words:
            return 0.0
        overlap = len(response_words & expected_words)
        return overlap / len(expected_words)

    def optimize(self, base_prompt: str, max_iterations: int = 5) -> Dict[str, Any]:
        """Iteratively optimize a prompt."""
        current_prompt = base_prompt
        best_prompt = base_prompt
        best_score = 0
        current_metrics = None

        for iteration in range(max_iterations):
            if current_metrics:
                metrics = current_metrics
            else:
                metrics = self.evaluate_prompt(current_prompt)

            self.results_history.append({
                'iteration': iteration,
                'prompt': current_prompt,
                'metrics': metrics
            })

            if metrics['avg_accuracy'] > best_score:
                best_score = metrics['avg_accuracy']
                best_prompt = current_prompt

            if metrics['avg_accuracy'] > 0.95:
                break

            variations = self.generate_variations(current_prompt, metrics)
            best_variation = current_prompt
            best_variation_score = metrics['avg_accuracy']
            best_variation_metrics = metrics

            for variation in variations:
                var_metrics = self.evaluate_prompt(variation)
                if var_metrics['avg_accuracy'] > best_variation_score:
                    best_variation_score = var_metrics['avg_accuracy']
                    best_variation = variation
                    best_variation_metrics = var_metrics

            current_prompt = best_variation
            current_metrics = best_variation_metrics

        return {
            'best_prompt': best_prompt,
            'best_score': best_score,
            'history': self.results_history
        }

    def generate_variations(self, prompt: str, current_metrics: Dict) -> List[str]:
        """Generate prompt variations to test."""
        variations = []
        variations.append(prompt + "\n\nProvide your answer in a clear, concise format.")
        variations.append("Let's solve this step by step.\n\n" + prompt)
        variations.append(prompt + "\n\nVerify your answer before responding.")
        return variations[:3]

    def export_results(self, filename: str):
        """Export optimization results to JSON."""
        with open(filename, 'w') as f:
            json.dump(self.results_history, f, indent=2)


def main():
    """Example usage."""
    test_suite = [
        TestCase(input={'text': 'This movie was amazing!'}, expected_output='Positive'),
        TestCase(input={'text': 'Worst purchase ever.'}, expected_output='Negative'),
        TestCase(input={'text': 'It was okay, nothing special.'}, expected_output='Neutral')
    ]

    class MockLLMClient:
        def complete(self, prompt):
            if 'amazing' in prompt:
                return 'Positive'
            elif 'worst' in prompt.lower():
                return 'Negative'
            return 'Neutral'

    optimizer = PromptOptimizer(MockLLMClient(), test_suite)

    try:
        base_prompt = "Classify the sentiment of: {text}\nSentiment:"
        results = optimizer.optimize(base_prompt)
        print(f"Best Accuracy: {results['best_score']:.2f}")
        optimizer.export_results('optimization_results.json')
    finally:
        optimizer.shutdown()


if __name__ == '__main__':
    main()
