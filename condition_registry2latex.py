#!/usr/bin/env python3
"""
Condition Registry to LaTeX Converter
Processes condition_registry.json and generates LaTeX tables with:
- Condition registry entries (type, description, evaluation)
- Condition usage summary
"""

import json
import os
import sys
from typing import Dict, List, Any, Optional


class ConditionRegistryToLaTeX:
    """Convert condition registry JSON to LaTeX tables"""
    
    def __init__(self, registry_file: str = "condition_registry.json", output_dir: str = "."):
        self.registry_file = registry_file
        self.output_dir = output_dir
        self.registry = {}
        self._load_registry()
    
    def _load_registry(self):
        """Load condition registry from JSON file"""
        if not os.path.exists(self.registry_file):
            print(f"[ERROR] File not found: {self.registry_file}")
            print("[INFO] Please run swm_generate.py first to generate condition_registry.json")
            sys.exit(1)
        
        try:
            with open(self.registry_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Handle both formats: direct condition_registry or wrapped
                if 'condition_registry' in data:
                    self.registry = data.get('condition_registry', {})
                else:
                    self.registry = data
            print(f"[OK] Loaded {len(self.registry)} conditions from {self.registry_file}")
        except Exception as e:
            print(f"[ERROR] Failed to load {self.registry_file}: {e}")
            sys.exit(1)
    
    def export_condition_table(self) -> str:
        """Export condition registry table"""
        lines = []
        lines.append("% Condition Registry Table")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Condition Registry}")
        lines.append("\\label{tab:condition_registry}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|c|l|}")
        lines.append("\\hline")
        lines.append("\\textbf{Condition} & \\textbf{Type} & \\textbf{Description / Evaluation} \\\\")
        lines.append("\\hline")
        
        for cond_name, cond_data in sorted(self.registry.items()):
            cond_type = cond_data.get('type', 'unknown')
            description = cond_data.get('description', '')
            
            if cond_type == 'function':
                evaluation = cond_data.get('evaluation', '')
                display = f"{description}\\newline\\texttt{{{evaluation}}}"
            elif cond_type == 'flag':
                flag_name = cond_data.get('flag_name', cond_name)
                display = f"{description}\\newline\\texttt{{flag: {flag_name}}}"
            elif cond_type == 'state':
                state_key = cond_data.get('state_key', cond_name)
                display = f"{description}\\newline\\texttt{{state: {state_key}}}"
            else:
                display = description or cond_name
            
            lines.append(f"\\texttt{{{cond_name}}} & \\texttt{{{cond_type}}} & {display} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_condition_summary(self) -> str:
        """Export condition summary statistics table"""
        lines = []
        lines.append("% Condition Summary Statistics")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Condition Registry Summary}")
        lines.append("\\label{tab:condition_summary}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|l|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Statistic} & \\textbf{Value} \\\\")
        lines.append("\\hline")
        
        lines.append(f"Total Conditions & {len(self.registry)} \\\\")
        lines.append("\\hline")
        
        # Count by type
        type_counts = {}
        for cond_data in self.registry.values():
            cond_type = cond_data.get('type', 'unknown')
            type_counts[cond_type] = type_counts.get(cond_type, 0) + 1
        
        lines.append("\\multicolumn{2}{|c|}{\\textbf{By Type}} \\\\")
        lines.append("\\hline")
        for cond_type, count in sorted(type_counts.items()):
            pct = (count / len(self.registry)) * 100 if self.registry else 0
            lines.append(f"\\texttt{{{cond_type}}} & {count} ({pct:.1f}\\%) \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_all(self):
        """Export all tables to individual LaTeX files"""
        tables = {
            "condition_registry.tex": self.export_condition_table(),
            "condition_summary.tex": self.export_condition_summary(),
        }
        
        print("\n" + "="*70)
        print("EXPORTING CONDITION REGISTRY LATEX TABLES")
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
        lines.append("% Condition Registry LaTeX Tables")
        lines.append("% Generated by condition_registry2latex.py")
        lines.append("% Input: " + self.registry_file)
        lines.append("")
        lines.append(self.export_condition_summary())
        lines.append("")
        lines.append(self.export_condition_table())
        
        filepath = os.path.join(self.output_dir, "condition_registry_tables.tex")
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f"[OK] Exported combined tables to: {filepath}")
        except Exception as e:
            print(f"[ERROR] Failed to export combined tables: {e}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Convert condition_registry.json to LaTeX tables',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python condition_registry2latex.py
  python condition_registry2latex.py --input condition_registry.json --output ./tables
  python condition_registry2latex.py --input world_tryal4/condition_registry.json --combined
        """
    )
    parser.add_argument('--input', '-i', type=str, default='condition_registry.json',
                        help='Path to condition_registry.json (default: condition_registry.json)')
    parser.add_argument('--output', '-o', type=str, default='.',
                        help='Output directory for LaTeX files (default: current directory)')
    parser.add_argument('--combined', '-c', action='store_true',
                        help='Export all tables into a single combined file')
    parser.add_argument('--list', '-l', action='store_true',
                        help='List available tables without exporting')
    
    args = parser.parse_args()
    
    print("="*70)
    print("CONDITION REGISTRY TO LATEX CONVERTER")
    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print("="*70)
    
    converter = ConditionRegistryToLaTeX(args.input, args.output)
    
    if args.list:
        print("\nAvailable Tables:")
        print("  - condition_registry.tex  : Full condition registry table")
        print("  - condition_summary.tex   : Summary statistics")
        return
    
    if args.combined:
        converter.export_combined()
    else:
        converter.export_all()


if __name__ == "__main__":
    main()