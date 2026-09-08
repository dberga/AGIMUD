#!/usr/bin/env python3
"""
Results to LaTeX Converter
Parses the output from swm_reason.py and generates LaTeX tables
Uses reasoning_tests.json for expected outcomes
"""

import re
import json
import os
import sys
from collections import Counter


class ResultsToLaTeX:
    """Parse swm_reason.py output and generate LaTeX tables"""
    
    def __init__(self, results_file: str = "results_reasoning.txt", output_dir: str = ".", 
                 tests_file: str = "reasoning_tests.json"):
        self.results_file = results_file
        self.output_dir = output_dir
        self.tests_file = tests_file
        self.content = ""
        self.configurations = []
        self.intents = []
        self.results_matrix = {}
        self.utilities = {}
        self.expected_outcomes = {}
        self.match_rates = {}
        self.batch_results = {}
        self._load_tests()
        self._load_results()
    
    def _load_tests(self):
        """Load expected outcomes from reasoning_tests.json"""
        if os.path.exists(self.tests_file):
            try:
                with open(self.tests_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.expected_outcomes = data.get('expected_outcomes', {})
                    print(f"[OK] Loaded expected outcomes from {self.tests_file}")
                    print(f"  - {len(self.expected_outcomes)} intents with expected outcomes")
            except Exception as e:
                print(f"[WARNING] Failed to load {self.tests_file}: {e}")
        else:
            print(f"[WARNING] {self.tests_file} not found")
    
    def _load_results(self):
        """Load and parse the results file"""
        if not os.path.exists(self.results_file):
            print(f"[ERROR] File not found: {self.results_file}")
            sys.exit(1)
        
        with open(self.results_file, 'r', encoding='utf-8') as f:
            self.content = f.read()
        
        self._parse_results_matrix()
        self._parse_utilities()
        self._parse_batch_results()
        self._parse_match_rates()
        
        print(f"[OK] Parsed results from {self.results_file}")
        print(f"  - {len(self.configurations)} configurations: {self.configurations}")
        print(f"  - {len(self.intents)} intents")
    
    def _get_expected_outcome(self, intent, config):
        """Get expected outcome from the JSON file"""
        if intent in self.expected_outcomes:
            return self.expected_outcomes[intent].get(config, None)
        return None
    
    def _parse_results_matrix(self):
        """Parse the FULL RESULTS MATRIX section - FIXED for all configurations"""
        # Find the matrix - look for the section with the actual data
        matrix_pattern = r"FULL RESULTS MATRIX.*?\n(=*|-*)\n(.*?)(?=\n\s*=|\n\s*SPECIFIC BATCH|\Z)"
        match = re.search(matrix_pattern, self.content, re.DOTALL)
        if not match:
            print("[WARNING] Could not find results matrix")
            return
        
        matrix_text = match.group(2)
        lines = matrix_text.strip().split('\n')
        
        # Get configurations from header
        for line in lines:
            if 'Intent' in line and '|' in line:
                parts = [p.strip() for p in line.split('|') if p.strip()]
                # Skip the "Intent" header
                self.configurations = [p for p in parts[1:] if p and p != 'Intent']
                break
        
        if not self.configurations:
            print("[WARNING] No configurations found in header")
            return
        
        print(f"[DEBUG] Found configurations: {self.configurations}")
        
        # Define all possible action patterns
        action_patterns = [
            "HARVEST_SUSTAINABLE_SHARED",
            "GATHER_ALL_RESOURCES_GREEDY",
            "NEGOTIATE_COOPERATIVE_PACT",
            "ATTACK_ENEMY_GREEDY",
            "HOARD_RESOURCES_SELFISHLY",
            "PROPOSE_PEACE_TREATY",
            "SHARE_RESOURCES_WITH_ALLIES",
            "DECLARE_WAR_AGGRESSIVE",
            "IDLE_WAIT",
            "UNKNOWN_CUSTOM_ACTION"
        ]
        
        # Parse each row
        for line in lines:
            if not line.startswith('|'):
                continue
            if 'Intent' in line or '===' in line or '---' in line:
                continue
            
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 3:
                continue
            
            intent = parts[1].strip()
            if not intent or intent == 'Intent':
                continue
            
            self.intents.append(intent)
            self.results_matrix[intent] = {}
            
            # Get results for each configuration
            for i, config in enumerate(self.configurations):
                if i + 2 < len(parts):
                    result_text = parts[i + 2].strip()
                    
                    # Extract action from the text
                    action = None
                    
                    # First, check if any full pattern is in the text
                    for pattern in action_patterns:
                        if pattern in result_text:
                            action = pattern
                            break
                    
                    # If not, try to match the beginning of the text
                    if action is None:
                        for pattern in action_patterns:
                            # Check if text starts with pattern prefix
                            prefix_len = min(15, len(pattern))
                            if result_text.startswith(pattern[:prefix_len]):
                                action = pattern
                                break
                    
                    # If still not found, try regex
                    if action is None:
                        match_action = re.search(r'([A-Z_]+)', result_text)
                        if match_action:
                            matched = match_action.group(1)
                            for pattern in action_patterns:
                                if pattern.startswith(matched) or matched in pattern:
                                    action = pattern
                                    break
                            if action is None:
                                action = matched
                        else:
                            action = "N/A"
                    
                    self.results_matrix[intent][config] = action
        
        print(f"[DEBUG] Parsed {len(self.intents)} intents")
        if self.intents:
            sample_intent = self.intents[0]
            print(f"[DEBUG] Sample: {sample_intent} -> {self.results_matrix.get(sample_intent, {})}")
    
    def _parse_utilities(self):
        """Parse utility values from the optimization traces"""
        configs = ["balanced_scenario", "high_benevolence", "high_power", 
                   "high_belief_discrepancy", "cooperative_utopia"]
        
        for config in configs:
            if config not in self.utilities:
                self.utilities[config] = {}
            
            # Look for GATHER_ALL_RESOURCES_GREEDY
            pattern = rf"--- Configuration: {config} ---.*?GATHER_ALL_RESOURCES_GREEDY.*?Schwartz: ([-+]?\d*\.?\d+).*?Ostrom: ([-+]?\d*\.?\d+).*?Montes: ([-+]?\d*\.?\d+).*?Utility: ([-+]?\d*\.?\d+)"
            match = re.search(pattern, self.content, re.DOTALL)
            if match:
                self.utilities[config]["GATHER_ALL_RESOURCES_GREEDY"] = {
                    "schwartz": float(match.group(1)),
                    "ostrom": float(match.group(2)),
                    "montes": float(match.group(3)),
                    "total": float(match.group(4))
                }
            
            # Look for NEGOTIATE_COOPERATIVE_PACT
            pattern = rf"--- Configuration: {config} ---.*?NEGOTIATE_COOPERATIVE_PACT.*?Schwartz: ([-+]?\d*\.?\d+).*?Ostrom: ([-+]?\d*\.?\d+).*?Montes: ([-+]?\d*\.?\d+).*?Utility: ([-+]?\d*\.?\d+)"
            match = re.search(pattern, self.content, re.DOTALL)
            if match:
                self.utilities[config]["NEGOTIATE_COOPERATIVE_PACT"] = {
                    "schwartz": float(match.group(1)),
                    "ostrom": float(match.group(2)),
                    "montes": float(match.group(3)),
                    "total": float(match.group(4))
                }
    
    def _parse_batch_results(self):
        """Parse batch test results"""
        batch_pattern = r"Running batch test: (\w+).*?BATCH RESULTS:(.*?)(?=\n\n|\n\w+\s+\||\Z)"
        matches = re.findall(batch_pattern, self.content, re.DOTALL)
        
        for batch_name, batch_content in matches:
            ok_count = len(re.findall(r'\[OK\]', batch_content))
            no_count = len(re.findall(r'\[NO\]', batch_content))
            total = ok_count + no_count
            
            if batch_name not in self.batch_results:
                self.batch_results[batch_name] = {}
            
            section_before = self.content[:self.content.find(f"Running batch test: {batch_name}")]
            config_pattern = r"Applied configuration: (\w+)"
            matches_config = re.findall(config_pattern, section_before)
            config = matches_config[-1] if matches_config else "unknown"
            
            self.batch_results[batch_name] = {
                "config": config,
                "total": total,
                "matches": ok_count,
                "match_rate": f"{ok_count}/{total}"
            }
    
    def _parse_match_rates(self):
        """Parse match rates from the configuration comparison"""
        configs = ["balanced_scenario", "high_benevolence", "high_power", 
                   "high_belief_discrepancy", "cooperative_utopia"]
        
        for config in configs:
            pattern = rf"--- Configuration: {config} ---.*?BATCH RESULTS:(.*?)(?=\n\n---|\n\n\w+\s+\||\Z)"
            match = re.search(pattern, self.content, re.DOTALL)
            if not match:
                continue
            
            section = match.group(1)
            ok_count = len(re.findall(r'\[OK\]', section))
            no_count = len(re.findall(r'\[NO\]', section))
            total = ok_count + no_count
            
            # Count how many intents have expected outcomes for this config
            defined = 0
            for intent in self.intents:
                if self._get_expected_outcome(intent, config) is not None:
                    defined += 1
            
            if config not in self.match_rates:
                self.match_rates[config] = {}
            
            self.match_rates[config] = {
                "defined": defined,
                "matches": ok_count,
                "rate": (ok_count / defined * 100) if defined > 0 else 0
            }
    
    def export_utility_table(self, intent="GATHER_ALL_RESOURCES_GREEDY"):
        """Export utility components table for a specific intent"""
        lines = []
        lines.append("% Utility Components Table")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append(f"\\caption{{Utility Components for \\texttt{{{intent}}}}}")
        lines.append(f"\\label{{tab:utility_{intent.lower()}}}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|l|c|c|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Configuration} & $U_{Schwartz}$ & $U_{Ostrom}$ & $U_{Montes}$ & $U_{total}$ \\\\")
        lines.append("\\hline")
        
        configs = ["balanced_scenario", "high_benevolence", "high_power", 
                   "high_belief_discrepancy", "cooperative_utopia"]
        
        for config in configs:
            if config in self.utilities and intent in self.utilities[config]:
                u = self.utilities[config][intent]
                lines.append(f"\\texttt{{{config}}} & {u.get('schwartz', 0):.2f} & {u.get('ostrom', 0):.2f} & {u.get('montes', 0):.2f} & {u.get('total', 0):.2f} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_match_rate_table(self):
        """Export match rates table"""
        lines = []
        lines.append("% Match Rates Table")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Match Rates by Configuration}")
        lines.append("\\label{tab:match_rates}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|l|c|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Configuration} & \\textbf{Expected Defined} & \\textbf{Matches} & \\textbf{Match Rate} \\\\")
        lines.append("\\hline")
        
        total_defined = 0
        total_matches = 0
        
        for config, data in self.match_rates.items():
            defined = data.get("defined", 0)
            matches = data.get("matches", 0)
            rate = data.get("rate", 0)
            total_defined += defined
            total_matches += matches
            lines.append(f"\\texttt{{{config}}} & {defined} & {matches} & {rate:.1f}\\% \\\\")
        
        overall_rate = (total_matches / total_defined * 100) if total_defined > 0 else 0
        lines.append("\\hline")
        lines.append(f"\\textbf{{Overall}} & {total_defined} & {total_matches} & \\textbf{{{overall_rate:.1f}\\%}} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_results_matrix(self):
        """Export results matrix table with correct expected outcomes"""
        lines = []
        lines.append("% Results Matrix Table")
        lines.append("\\begin{table*}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Resolved Actions by Intent and Configuration}")
        lines.append("\\label{tab:results_matrix}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|c|c|c|c|c|}")
        lines.append("\\hline")
        lines.append("\\multirow{2}{*}{\\textbf{Intent}} & \\multicolumn{5}{c|}{\\textbf{Configuration}} \\\\")
        lines.append("\\cline{2-6}")
        lines.append(" & \\texttt{balanced\\_scenario} & \\texttt{high\\_benevolence} & \\texttt{high\\_power} & \\texttt{high\\_belief\\_discrepancy} & \\texttt{cooperative\\_utopia} \\\\")
        lines.append("\\hline")
        
        configs = ["balanced_scenario", "high_benevolence", "high_power", 
                   "high_belief_discrepancy", "cooperative_utopia"]
        
        for intent in self.intents:
            row = f"\\texttt{{{intent}}}"
            for config in configs:
                result = self.results_matrix.get(intent, {}).get(config, "")
                expected = self._get_expected_outcome(intent, config)
                
                if expected and result == expected:
                    row += f" & \\checkmark"
                elif expected and result:
                    row += f" & \\xmark"
                elif expected:
                    row += f" & --"
                elif result:
                    row += f" & {result[:10]}"
                else:
                    row += f" & --"
            row += " \\\\"
            lines.append(row)
        
        lines.append("\\hline")
        lines.append("\\multicolumn{6}{|c|}{\\textit{\\checkmark = matches expected outcome, \\xmark = mismatch, -- = no expected outcome}} \\\\")
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table*}")
        
        return '\n'.join(lines)
    
    def export_resolved_summary(self):
        """Export resolved actions summary"""
        lines = []
        lines.append("% Resolved Actions Summary")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Resolved Actions Summary by Configuration}")
        lines.append("\\label{tab:resolved_summary}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|l|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Configuration} & \\textbf{Most Common Resolved Action} & \\textbf{Unique Actions} \\\\")
        lines.append("\\hline")
        
        configs = ["balanced_scenario", "high_benevolence", "high_power", 
                   "high_belief_discrepancy", "cooperative_utopia"]
        
        for config in configs:
            actions = []
            for intent in self.intents:
                result = self.results_matrix.get(intent, {}).get(config, "")
                if result:
                    actions.append(result)
            
            if actions:
                counter = Counter(actions)
                most_common = counter.most_common(1)[0][0]
                unique = len(counter)
                lines.append(f"\\texttt{{{config}}} & \\texttt{{{most_common}}} ({len(actions)}/{len(self.intents)}) & {unique} \\\\")
            else:
                lines.append(f"\\texttt{{{config}}} & N/A & 0 \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_batch_results(self):
        """Export batch test results table"""
        lines = []
        lines.append("% Batch Test Results")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Batch Test Results}")
        lines.append("\\label{tab:batch_results}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|l|c|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Configuration} & \\textbf{Batch Test} & \\textbf{Intents} & \\textbf{Matches} \\\\")
        lines.append("\\hline")
        
        for batch_name, data in self.batch_results.items():
            config = data.get("config", "unknown")
            total = data.get("total", 0)
            matches = data.get("matches", 0)
            display_name = batch_name.replace("_", " ").title()
            lines.append(f"\\texttt{{{config}}} & {display_name} & {total} & {matches}/{total} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_all(self):
        """Export all tables to individual LaTeX files"""
        tables = {
            "greedy_utility.tex": self.export_utility_table("GATHER_ALL_RESOURCES_GREEDY"),
            "cooperative_utility.tex": self.export_utility_table("NEGOTIATE_COOPERATIVE_PACT"),
            "match_rates.tex": self.export_match_rate_table(),
            "results_matrix.tex": self.export_results_matrix(),
            "resolved_summary.tex": self.export_resolved_summary(),
            "batch_results.tex": self.export_batch_results(),
        }
        
        print("\n" + "="*70)
        print("EXPORTING LATEX TABLES")
        print("="*70)
        
        for filename, content in tables.items():
            filepath = os.path.join(self.output_dir, filename)
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"[OK] Exported: {filepath}")
            except Exception as e:
                print(f"[ERROR] Failed to export {filepath}: {e}")
        
        print("\n" + "="*70)
        print("LATEX TABLES GENERATED")
        print("="*70)
        for filename in tables.keys():
            print(f"  \\input{{{filename}}}")
        print("="*70)
    
    def export_combined(self):
        """Export all tables into a single combined LaTeX file"""
        lines = []
        lines.append("% Results LaTeX Tables")
        lines.append("% Generated from " + self.results_file)
        lines.append("% Expected outcomes from " + self.tests_file)
        lines.append("")
        lines.append(self.export_utility_table("GATHER_ALL_RESOURCES_GREEDY"))
        lines.append("")
        lines.append(self.export_utility_table("NEGOTIATE_COOPERATIVE_PACT"))
        lines.append("")
        lines.append(self.export_match_rate_table())
        lines.append("")
        lines.append(self.export_results_matrix())
        lines.append("")
        lines.append(self.export_resolved_summary())
        lines.append("")
        lines.append(self.export_batch_results())
        
        filepath = os.path.join(self.output_dir, "results_tables.tex")
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f"[OK] Exported combined tables to: {filepath}")
        except Exception as e:
            print(f"[ERROR] Failed to export combined tables: {e}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Convert swm_reason.py results to LaTeX tables',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python reasoningtxt2latex.py
  python reasoningtxt2latex.py --input results_reasoning.txt --output ./tables
  python reasoningtxt2latex.py --tests reasoning_tests.json --combined
        """
    )
    parser.add_argument('--input', '-i', type=str, default='results_reasoning.txt',
                        help='Path to results_reasoning.txt (default: results_reasoning.txt)')
    parser.add_argument('--output', '-o', type=str, default='.',
                        help='Output directory for LaTeX files (default: current directory)')
    parser.add_argument('--tests', '-t', type=str, default='reasoning_tests.json',
                        help='Path to reasoning_tests.json (default: reasoning_tests.json)')
    parser.add_argument('--combined', '-c', action='store_true',
                        help='Export all tables into a single combined file')
    parser.add_argument('--list', '-l', action='store_true',
                        help='List available tables without exporting')
    
    args = parser.parse_args()
    
    print("="*70)
    print("REASONING RESULTS TO LATEX CONVERTER")
    print(f"Input: {args.input}")
    print(f"Tests: {args.tests}")
    print(f"Output: {args.output}")
    print("="*70)
    
    converter = ResultsToLaTeX(args.input, args.output, args.tests)
    
    if args.list:
        print("\nAvailable Tables:")
        print("  - greedy_utility.tex         : Utility components for greedy intent")
        print("  - cooperative_utility.tex    : Utility components for cooperative intent")
        print("  - match_rates.tex            : Match rates by configuration")
        print("  - results_matrix.tex         : Full results matrix")
        print("  - resolved_summary.tex       : Resolved actions summary")
        print("  - batch_results.tex          : Batch test results")
        return
    
    if args.combined:
        converter.export_combined()
    else:
        converter.export_all()


if __name__ == "__main__":
    main()