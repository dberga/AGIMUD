#!/usr/bin/env python3
"""
Rules to LaTeX Converter
Processes rules.json and generates LaTeX tables with:
- Rule categories (condition, transition, mechanic, emotion, reasoning, behavior_graph, scene_graph)
- Rule details and parameters
- Summary statistics
"""

import json
import os
import sys
from typing import Dict, List, Any, Optional
from collections import Counter


class RulesToLaTeX:
    """Convert rules JSON to LaTeX tables"""
    
    def __init__(self, rules_file: str = "rules.json", output_dir: str = "."):
        self.rules_file = rules_file
        self.output_dir = output_dir
        self.rules = []
        self._load_rules()
    
    def _load_rules(self):
        """Load rules from JSON file"""
        if not os.path.exists(self.rules_file):
            print(f"[ERROR] File not found: {self.rules_file}")
            print("[INFO] Please run swm_generate.py first to generate rules.json")
            sys.exit(1)
        
        try:
            with open(self.rules_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Handle both formats: direct rules list or wrapped
                if 'rules' in data:
                    self.rules = data.get('rules', [])
                else:
                    self.rules = data
            print(f"[OK] Loaded {len(self.rules)} rules from {self.rules_file}")
        except Exception as e:
            print(f"[ERROR] Failed to load {self.rules_file}: {e}")
            sys.exit(1)
    
    def export_rule_summary(self) -> str:
        """Export rule summary statistics table"""
        lines = []
        lines.append("% Rule Summary Statistics")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Rules Summary}")
        lines.append("\\label{tab:rules_summary}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|l|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Statistic} & \\textbf{Value} \\\\")
        lines.append("\\hline")
        
        lines.append(f"Total Rules & {len(self.rules)} \\\\")
        lines.append("\\hline")
        
        # Count by type
        type_counts = {}
        for rule in self.rules:
            rule_type = rule.get('type', 'unknown')
            type_counts[rule_type] = type_counts.get(rule_type, 0) + 1
        
        lines.append("\\multicolumn{2}{|c|}{\\textbf{By Type}} \\\\")
        lines.append("\\hline")
        for rule_type, count in sorted(type_counts.items()):
            pct = (count / len(self.rules)) * 100 if self.rules else 0
            lines.append(f"\\texttt{{{rule_type}}} & {count} ({pct:.1f}\\%) \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_condition_rules(self) -> str:
        """Export condition rules table"""
        lines = []
        lines.append("% Condition Rules")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Condition Rules}")
        lines.append("\\label{tab:condition_rules}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|l|p{6cm}|}")
        lines.append("\\hline")
        lines.append("\\textbf{ID} & \\textbf{Name} & \\textbf{Conditions} \\\\")
        lines.append("\\hline")
        
        for rule in self.rules:
            if rule.get('type') != 'condition':
                continue
            
            rule_id = rule.get('id', 'N/A')
            name = rule.get('name', 'N/A')
            description = rule.get('description', '')
            
            # Format conditions
            conditions = rule.get('conditions', [])
            cond_strs = []
            for cond in conditions:
                cond_type = cond.get('type', '')
                field = cond.get('field', '')
                value = cond.get('value', '')
                if cond_type == 'greater_than':
                    cond_strs.append(f"\\texttt{{{field} > {value}}}")
                elif cond_type == 'less_than':
                    cond_strs.append(f"\\texttt{{{field} < {value}}}")
                elif cond_type == 'equal':
                    cond_strs.append(f"\\texttt{{{field} == {value}}}")
                elif cond_type == 'not_equal':
                    cond_strs.append(f"\\texttt{{{field} != {value}}}")
                elif cond_type == 'contains':
                    cond_strs.append(f"\\texttt{{{field} contains '{value}'}}")
                else:
                    cond_strs.append(f"\\texttt{{{cond_type}}}")
            
            cond_display = " \\\\ ".join(cond_strs) if cond_strs else description
            
            lines.append(f"\\texttt{{{rule_id}}} & {name} & {cond_display} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_transition_rules(self) -> str:
        """Export transition rules table"""
        lines = []
        lines.append("% Transition Rules")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Transition Rules}")
        lines.append("\\label{tab:transition_rules}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|l|c|c|l|}")
        lines.append("\\hline")
        lines.append("\\textbf{ID} & \\textbf{Name} & \\textbf{From} & \\textbf{To} & \\textbf{Conditions} \\\\")
        lines.append("\\hline")
        
        for rule in self.rules:
            if rule.get('type') != 'transition':
                continue
            
            rule_id = rule.get('id', 'N/A')
            name = rule.get('name', 'N/A')
            from_state = rule.get('from_state', 'N/A')
            to_state = rule.get('to_state', 'N/A')
            
            # Format conditions
            conditions = rule.get('conditions', [])
            cond_strs = []
            for cond in conditions:
                cond_type = cond.get('type', '')
                field = cond.get('field', '')
                value = cond.get('value', '')
                if cond_type == 'greater_than':
                    cond_strs.append(f"\\texttt{{{field} > {value}}}")
                elif cond_type == 'less_than':
                    cond_strs.append(f"\\texttt{{{field} < {value}}}")
                elif cond_type == 'equal':
                    cond_strs.append(f"\\texttt{{{field} == {value}}}")
                elif cond_type == 'not_equal':
                    cond_strs.append(f"\\texttt{{{field} != {value}}}")
                elif cond_type == 'contains':
                    cond_strs.append(f"\\texttt{{{field} contains '{value}'}}")
                else:
                    cond_strs.append(f"\\texttt{{{cond_type}}}")
            
            cond_display = " \\\\ ".join(cond_strs) if cond_strs else "No conditions"
            
            lines.append(f"\\texttt{{{rule_id}}} & {name} & \\texttt{{{from_state}}} & \\texttt{{{to_state}}} & {cond_display} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_mechanic_rules(self) -> str:
        """Export mechanic rules table"""
        lines = []
        lines.append("% Mechanic Rules")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Mechanic Rules}")
        lines.append("\\label{tab:mechanic_rules}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|l|l|p{4cm}|}")
        lines.append("\\hline")
        lines.append("\\textbf{ID} & \\textbf{Name} & \\textbf{Conditions} & \\textbf{Effects} \\\\")
        lines.append("\\hline")
        
        for rule in self.rules:
            if rule.get('type') != 'mechanic':
                continue
            
            rule_id = rule.get('id', 'N/A')
            name = rule.get('name', 'N/A')
            
            # Format conditions
            conditions = rule.get('conditions', [])
            cond_strs = []
            for cond in conditions:
                cond_type = cond.get('type', '')
                field = cond.get('field', '')
                value = cond.get('value', '')
                if cond_type == 'greater_than':
                    cond_strs.append(f"\\texttt{{{field} > {value}}}")
                elif cond_type == 'less_than':
                    cond_strs.append(f"\\texttt{{{field} < {value}}}")
                elif cond_type == 'equal':
                    cond_strs.append(f"\\texttt{{{field} == {value}}}")
                elif cond_type == 'not_equal':
                    cond_strs.append(f"\\texttt{{{field} != {value}}}")
                elif cond_type == 'contains':
                    cond_strs.append(f"\\texttt{{{field} contains '{value}'}}")
                else:
                    cond_strs.append(f"\\texttt{{{cond_type}}}")
            
            cond_display = " \\\\ ".join(cond_strs) if cond_strs else "No conditions"
            
            # Format effects
            effects = rule.get('effects', [])
            effect_strs = []
            for eff in effects:
                eff_type = eff.get('type', '')
                target = eff.get('target', '')
                if eff_type == 'modify':
                    delta = eff.get('delta', 0)
                    effect_strs.append(f"\\texttt{{{target} += {delta}}}")
                elif eff_type == 'set':
                    value = eff.get('value', '')
                    effect_strs.append(f"\\texttt{{{target} = {value}}}")
                elif eff_type == 'remove':
                    value = eff.get('value', '')
                    effect_strs.append(f"\\texttt{{remove {value} from {target}}}")
                else:
                    effect_strs.append(f"\\texttt{{{eff_type}}}")
            
            effect_display = " \\\\ ".join(effect_strs) if effect_strs else "No effects"
            
            lines.append(f"\\texttt{{{rule_id}}} & {name} & {cond_display} & {effect_display} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_emotion_rules(self) -> str:
        """Export emotion rules table"""
        lines = []
        lines.append("% Emotion Rules")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Emotion Rules (Ekman Model)}")
        lines.append("\\label{tab:emotion_rules}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|l|c|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Emotion} & \\textbf{Trigger} & \\textbf{Action} & \\textbf{Priority} & \\textbf{Arousal} \\\\")
        lines.append("\\hline")
        
        for rule in self.rules:
            if rule.get('type') != 'emotion':
                continue
            
            emotion_mapping = rule.get('emotion_mapping', {})
            appraisal_rules = rule.get('appraisal_rules', [])
            
            # Build mapping from appraisal rules
            for appraisal in appraisal_rules:
                emotion = appraisal.get('emotion', 'N/A')
                trigger = appraisal.get('trigger', 'N/A')
                action = appraisal.get('action', 'N/A')
                
                # Get priority and arousal from emotion_mapping
                mapping = emotion_mapping.get(emotion, {})
                priority = mapping.get('priority', 'N/A')
                arousal = mapping.get('arousal', 'N/A')
                
                lines.append(f"{emotion.title()} & \\texttt{{{trigger}}} & \\texttt{{{action}}} & {priority} & {arousal} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_reasoning_rules(self) -> str:
        """Export reasoning rules table"""
        lines = []
        lines.append("% Reasoning Rules")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Reasoning Rules (Schwartz, Ostrom, Montes-Sierra)}")
        lines.append("\\label{tab:reasoning_rules}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|l|l|}")
        lines.append("\\hline")
        lines.append("\\textbf{ID} & \\textbf{Name} & \\textbf{Configuration} \\\\")
        lines.append("\\hline")
        
        for rule in self.rules:
            if rule.get('type') != 'reasoning':
                continue
            
            rule_id = rule.get('id', 'N/A')
            name = rule.get('name', 'N/A')
            description = rule.get('description', '')
            
            # Collect configuration details
            config_parts = []
            
            if 'schwartz_weights' in rule:
                weights = rule['schwartz_weights']
                top_vals = sorted(weights.items(), key=lambda x: x[1], reverse=True)[:3]
                config_parts.append(f"Schwartz: {', '.join([f'{k}={v:.1f}' for k, v in top_vals])}")
            
            if 'ostrom_weights' in rule:
                weights = rule['ostrom_weights']
                config_parts.append(f"Ostrom: {', '.join([f'{k}={v:.1f}' for k, v in weights.items()])}")
            
            if 'beliefs' in rule:
                beliefs = rule['beliefs']
                config_parts.append(f"Beliefs: {', '.join([f'{k}={v:.1f}' for k, v in list(beliefs.items())[:3]])}")
            
            if 'trust_threshold' in rule:
                config_parts.append(f"Trust: {rule['trust_threshold']}")
            
            config_display = "\\\\ ".join(config_parts) if config_parts else description
            
            lines.append(f"\\texttt{{{rule_id}}} & {name} & {config_display} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_behavior_graph_rules(self) -> str:
        """Export behavior graph rules table"""
        lines = []
        lines.append("% Behavior Graph Rules")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Behavior Graph Rules}")
        lines.append("\\label{tab:behavior_graph_rules}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|l|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{ID} & \\textbf{Name} & \\textbf{Nodes} & \\textbf{Edges} \\\\")
        lines.append("\\hline")
        
        for rule in self.rules:
            if rule.get('type') != 'behavior_graph':
                continue
            
            rule_id = rule.get('id', 'N/A')
            name = rule.get('name', 'N/A')
            nodes = rule.get('graph_nodes', [])
            edges = rule.get('graph_edges', [])
            
            node_ids = ", ".join([n.get('id', '') for n in nodes])
            edges_str = ", ".join([f"{e.get('from')}->{e.get('to')}" for e in edges[:5]])
            if len(edges) > 5:
                edges_str += f", ... ({len(edges)} total)"
            
            lines.append(f"\\texttt{{{rule_id}}} & {name} & {len(nodes)} nodes & {len(edges)} edges \\\\")
            lines.append(f" & & \\multicolumn{{2}}{{l|}}{{\\textit{{Nodes: {node_ids}}}}} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_scene_graph_rules(self) -> str:
        """Export scene graph rules table"""
        lines = []
        lines.append("% Scene Graph Rules")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Scene Graph Rules}")
        lines.append("\\label{tab:scene_graph_rules}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|l|c|c|l|}")
        lines.append("\\hline")
        lines.append("\\textbf{ID} & \\textbf{Name} & \\textbf{Nodes} & \\textbf{Edges} & \\textbf{Algorithm} \\\\")
        lines.append("\\hline")
        
        for rule in self.rules:
            if rule.get('type') != 'scene_graph':
                continue
            
            rule_id = rule.get('id', 'N/A')
            name = rule.get('name', 'N/A')
            nodes = rule.get('graph_nodes', [])
            edges = rule.get('graph_edges', [])
            pathfinding = rule.get('pathfinding', {})
            algorithm = pathfinding.get('algorithm', 'N/A')
            
            node_ids = ", ".join([n.get('id', '') for n in nodes])
            
            lines.append(f"\\texttt{{{rule_id}}} & {name} & {len(nodes)} nodes & {len(edges)} edges & \\texttt{{{algorithm}}} \\\\")
            lines.append(f" & & \\multicolumn{{3}}{{l|}}{{\\textit{{Nodes: {node_ids}}}}} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_all(self):
        """Export all tables to individual LaTeX files"""
        tables = {
            "rules_summary.tex": self.export_rule_summary(),
            "condition_rules.tex": self.export_condition_rules(),
            "transition_rules.tex": self.export_transition_rules(),
            "mechanic_rules.tex": self.export_mechanic_rules(),
            "emotion_rules.tex": self.export_emotion_rules(),
            "reasoning_rules.tex": self.export_reasoning_rules(),
            "behavior_graph_rules.tex": self.export_behavior_graph_rules(),
            "scene_graph_rules.tex": self.export_scene_graph_rules(),
        }
        
        print("\n" + "="*70)
        print("EXPORTING RULES LATEX TABLES")
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
        lines.append("% Rules LaTeX Tables")
        lines.append("% Generated by rules2latex.py")
        lines.append("% Input: " + self.rules_file)
        lines.append("")
        lines.append(self.export_rule_summary())
        lines.append("")
        lines.append(self.export_condition_rules())
        lines.append("")
        lines.append(self.export_transition_rules())
        lines.append("")
        lines.append(self.export_mechanic_rules())
        lines.append("")
        lines.append(self.export_emotion_rules())
        lines.append("")
        lines.append(self.export_reasoning_rules())
        lines.append("")
        lines.append(self.export_behavior_graph_rules())
        lines.append("")
        lines.append(self.export_scene_graph_rules())
        
        filepath = os.path.join(self.output_dir, "rules_tables.tex")
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f"[OK] Exported combined tables to: {filepath}")
        except Exception as e:
            print(f"[ERROR] Failed to export combined tables: {e}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Convert rules.json to LaTeX tables',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python rules2latex.py
  python rules2latex.py --input rules.json --output ./tables
  python rules2latex.py --input world_tryal4/rules.json --combined
        """
    )
    parser.add_argument('--input', '-i', type=str, default='rules.json',
                        help='Path to rules.json (default: rules.json)')
    parser.add_argument('--output', '-o', type=str, default='.',
                        help='Output directory for LaTeX files (default: current directory)')
    parser.add_argument('--combined', '-c', action='store_true',
                        help='Export all tables into a single combined file')
    parser.add_argument('--list', '-l', action='store_true',
                        help='List available tables without exporting')
    
    args = parser.parse_args()
    
    print("="*70)
    print("RULES TO LATEX CONVERTER")
    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print("="*70)
    
    converter = RulesToLaTeX(args.input, args.output)
    
    if args.list:
        print("\nAvailable Tables:")
        print("  - rules_summary.tex         : Summary statistics")
        print("  - condition_rules.tex       : Condition rules")
        print("  - transition_rules.tex      : Transition rules")
        print("  - mechanic_rules.tex        : Mechanic rules")
        print("  - emotion_rules.tex         : Emotion rules (Ekman model)")
        print("  - reasoning_rules.tex       : Reasoning rules (Schwartz, Ostrom, Montes-Sierra)")
        print("  - behavior_graph_rules.tex  : Behavior graph rules")
        print("  - scene_graph_rules.tex     : Scene graph rules")
        return
    
    if args.combined:
        converter.export_combined()
    else:
        converter.export_all()


if __name__ == "__main__":
    main()