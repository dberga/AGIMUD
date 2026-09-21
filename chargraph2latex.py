#!/usr/bin/env python3
"""
Character Graph to LaTeX Converter
Processes character_graph.json and generates LaTeX tables with:
- Character properties (faction, alignment, Schwartz values)
- Relationship edges (trust, type, weight, similarity)
- Summary statistics
"""

import json
import os
import sys
from typing import Dict, List, Any, Optional
from collections import Counter, defaultdict


class CharGraphToLaTeX:
    """Convert character graph JSON to LaTeX tables"""
    
    def __init__(self, graph_file: str = "character_graph.json", output_dir: str = "."):
        self.graph_file = graph_file
        self.output_dir = output_dir
        self.graph = None
        self.nodes = []
        self.edges = []
        self._load_graph()
    
    def _load_graph(self):
        """Load character graph from JSON file"""
        if not os.path.exists(self.graph_file):
            print(f"[ERROR] File not found: {self.graph_file}")
            print("[INFO] Please run swm_generate.py first to generate character_graph.json")
            sys.exit(1)
        
        try:
            with open(self.graph_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.graph = data.get('character_graph', {})
                self.nodes = self.graph.get('nodes', [])
                self.edges = self.graph.get('edges', [])
            print(f"[OK] Loaded {len(self.nodes)} characters and {len(self.edges)} relationships")
        except Exception as e:
            print(f"[ERROR] Failed to load {self.graph_file}: {e}")
            sys.exit(1)
    
    def export_character_table(self) -> str:
        """Export character properties table"""
        lines = []
        lines.append("% Character Properties Table")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Character Properties (Faction, Alignment \\& Schwartz Values)}")
        lines.append("\\label{tab:character_properties}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|c|c|c|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Character} & \\textbf{Faction} & \\textbf{Alignment} & \\textbf{Primary Value} & \\textbf{Secondary Value} & \\textbf{Emotion} \\\\")
        lines.append("\\hline")
        
        for node in self.nodes:
            name = node.get('id', 'Unknown')
            faction = node.get('faction', 'N/A')
            alignment = node.get('alignment', 'N/A')
            
            schwartz = node.get('schwartz_values', {})
            if schwartz:
                # Sort by value descending
                sorted_vals = sorted(schwartz.items(), key=lambda x: x[1], reverse=True)
                primary = f"{sorted_vals[0][0].replace('_', ' ').title()} ({sorted_vals[0][1]:.2f})"
                secondary = f"{sorted_vals[1][0].replace('_', ' ').title()} ({sorted_vals[1][1]:.2f})" if len(sorted_vals) > 1 else "N/A"
            else:
                primary = "N/A"
                secondary = "N/A"
            
            # Get emotion from character graph (if available)
            emotion = node.get('emotion', 'neutral')
            
            lines.append(f"{name} & {faction} & {alignment} & {primary} & {secondary} & {emotion} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_schwartz_table(self) -> str:
        """Export full Schwartz values table"""
        lines = []
        lines.append("% Schwartz Values Table (All 10 Values)")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Schwartz Values by Character}")
        lines.append("\\label{tab:schwartz_values}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|c|c|c|c|c|c|c|c|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Character} & \\textbf{SD} & \\textbf{ST} & \\textbf{HE} & \\textbf{AC} & \\textbf{PO} & \\textbf{SE} & \\textbf{CO} & \\textbf{TR} & \\textbf{BE} & \\textbf{UN} \\\\")
        lines.append("\\hline")
        
        # Schwartz value labels
        labels = {
            'self_direction': 'SD',
            'stimulation': 'ST',
            'hedonism': 'HE',
            'achievement': 'AC',
            'power': 'PO',
            'security': 'SE',
            'conformity': 'CO',
            'tradition': 'TR',
            'benevolence': 'BE',
            'universalism': 'UN'
        }
        
        for node in self.nodes:
            name = node.get('id', 'Unknown')
            schwartz = node.get('schwartz_values', {})
            
            values = []
            for key in labels.keys():
                values.append(f"{schwartz.get(key, 0.0):.2f}")
            
            lines.append(f"{name} & " + " & ".join(values) + " \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_relationship_table(self) -> str:
        """Export relationship edges table"""
        lines = []
        lines.append("% Relationship Edges Table")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Character Relationships (Trust, Type, Weight, Similarity)}")
        lines.append("\\label{tab:relationships}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        lines.append("\\begin{tabular}{|l|l|c|c|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{From} & \\textbf{To} & \\textbf{Type} & \\textbf{Trust} & \\textbf{Weight} & \\textbf{Similarity} \\\\")
        lines.append("\\hline")
        
        for edge in self.edges:
            from_name = edge.get('from', 'Unknown')
            to_name = edge.get('to', 'Unknown')
            edge_type = edge.get('type', 'neutral')
            trust = edge.get('trust', 0.5)
            weight = edge.get('weight', 0.5)
            similarity = edge.get('similarity', 0.5)
            
            lines.append(f"{from_name} & {to_name} & {edge_type} & {trust:.2f} & {weight:.2f} & {similarity:.2f} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_summary_statistics(self) -> str:
        """Export summary statistics table"""
        lines = []
        lines.append("% Summary Statistics")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Relationship Summary Statistics}")
        lines.append("\\label{tab:relationship_summary}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|l|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Statistic} & \\textbf{Value} \\\\")
        lines.append("\\hline")
        
        # Count relationship types
        type_counts = Counter([e.get('type', 'neutral') for e in self.edges])
        
        lines.append(f"Total Characters & {len(self.nodes)} \\\\")
        lines.append(f"Total Relationships & {len(self.edges)} \\\\")
        lines.append("\\hline")
        lines.append("\\multicolumn{2}{|c|}{\\textbf{Relationship Types}} \\\\")
        lines.append("\\hline")
        
        for rel_type, count in type_counts.most_common():
            pct = (count / len(self.edges)) * 100 if self.edges else 0
            lines.append(f"{rel_type.title()} & {count} ({pct:.1f}\\%) \\\\")
        
        lines.append("\\hline")
        lines.append("\\multicolumn{2}{|c|}{\\textbf{Faction Distribution}} \\\\")
        lines.append("\\hline")
        
        faction_counts = Counter([n.get('faction', 'Unknown') for n in self.nodes])
        for faction, count in faction_counts.most_common():
            pct = (count / len(self.nodes)) * 100 if self.nodes else 0
            lines.append(f"{faction} & {count} ({pct:.1f}\\%) \\\\")
        
        lines.append("\\hline")
        lines.append("\\multicolumn{2}{|c|}{\\textbf{Alignment Distribution}} \\\\")
        lines.append("\\hline")
        
        alignment_counts = Counter([n.get('alignment', 'Unknown') for n in self.nodes])
        for alignment, count in alignment_counts.most_common():
            pct = (count / len(self.nodes)) * 100 if self.nodes else 0
            lines.append(f"{alignment.replace('_', ' ')} & {count} ({pct:.1f}\\%) \\\\")
        
        # Average statistics
        avg_trust = sum(e.get('trust', 0) for e in self.edges) / len(self.edges) if self.edges else 0
        avg_weight = sum(e.get('weight', 0) for e in self.edges) / len(self.edges) if self.edges else 0
        avg_similarity = sum(e.get('similarity', 0) for e in self.edges) / len(self.edges) if self.edges else 0
        
        lines.append("\\hline")
        lines.append("\\multicolumn{2}{|c|}{\\textbf{Average Values}} \\\\")
        lines.append("\\hline")
        lines.append(f"Average Trust & {avg_trust:.3f} \\\\")
        lines.append(f"Average Weight & {avg_weight:.3f} \\\\")
        lines.append(f"Average Similarity & {avg_similarity:.3f} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_trust_matrix(self) -> str:
        """Export trust matrix between characters"""
        lines = []
        lines.append("% Trust Matrix")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Trust Matrix Between Characters}")
        lines.append("\\label{tab:trust_matrix}")
        lines.append("\\begin{adjustbox}{width=\\textwidth}")
        
        # Get all character names
        names = [n.get('id', 'Unknown') for n in self.nodes]
        
        # Build trust matrix
        trust_matrix = {}
        for edge in self.edges:
            from_name = edge.get('from', '')
            to_name = edge.get('to', '')
            trust = edge.get('trust', 0.5)
            
            if from_name not in trust_matrix:
                trust_matrix[from_name] = {}
            trust_matrix[from_name][to_name] = trust
            
            # Also add reverse direction
            if to_name not in trust_matrix:
                trust_matrix[to_name] = {}
            trust_matrix[to_name][from_name] = trust
        
        # Build table
        cols = len(names) + 1
        col_spec = "|l|" + "c|" * len(names)
        lines.append(f"\\begin{{tabular}}{{{col_spec}}}")
        lines.append("\\hline")
        
        # Header row
        header = "\\textbf{From $\\to$ To} & " + " & ".join([f"\\textbf{{{n}}}" for n in names]) + " \\\\"
        lines.append(header)
        lines.append("\\hline")
        
        # Data rows
        for from_name in names:
            row = [f"\\textbf{{{from_name}}}"]
            for to_name in names:
                if from_name == to_name:
                    row.append("-")
                else:
                    trust = trust_matrix.get(from_name, {}).get(to_name, 0.0)
                    # Color code trust values
                    if trust >= 0.7:
                        row.append(f"\\textcolor{{green}}{{{trust:.2f}}}")
                    elif trust >= 0.4:
                        row.append(f"{trust:.2f}")
                    else:
                        row.append(f"\\textcolor{{red}}{{{trust:.2f}}}")
            lines.append(" & ".join(row) + " \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\caption*{\\textit{Green = High Trust ($\\ge$0.7), Red = Low Trust ($<$0.4)}}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_faction_network(self) -> str:
        """Export faction network summary"""
        lines = []
        lines.append("% Faction Network Summary")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Faction Network Summary}")
        lines.append("\\label{tab:faction_network}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|l|c|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Faction} & \\textbf{Members} & \\textbf{Internal Edges} & \\textbf{External Edges} \\\\")
        lines.append("\\hline")
        
        # Group characters by faction
        faction_members = defaultdict(list)
        for node in self.nodes:
            faction = node.get('faction', 'Unknown')
            faction_members[faction].append(node.get('id', 'Unknown'))
        
        # Count internal vs external edges per faction
        faction_internal = defaultdict(int)
        faction_external = defaultdict(int)
        
        for edge in self.edges:
            from_name = edge.get('from', '')
            to_name = edge.get('to', '')
            
            # Find factions
            from_faction = None
            to_faction = None
            for node in self.nodes:
                if node.get('id') == from_name:
                    from_faction = node.get('faction', 'Unknown')
                if node.get('id') == to_name:
                    to_faction = node.get('faction', 'Unknown')
            
            if from_faction and to_faction:
                if from_faction == to_faction:
                    faction_internal[from_faction] += 1
                else:
                    faction_external[from_faction] += 1
                    faction_external[to_faction] += 1
        
        for faction, members in faction_members.items():
            internal = faction_internal.get(faction, 0)
            external = faction_external.get(faction, 0)
            members_str = ", ".join(members)
            lines.append(f"{faction} & {len(members)} & {internal} & {external} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_all(self):
        """Export all tables to individual LaTeX files"""
        tables = {
            "character_properties.tex": self.export_character_table(),
            "schwartz_values.tex": self.export_schwartz_table(),
            "relationships.tex": self.export_relationship_table(),
            "relationship_summary.tex": self.export_summary_statistics(),
            "trust_matrix.tex": self.export_trust_matrix(),
            "faction_network.tex": self.export_faction_network(),
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
        lines.append("% Character Graph LaTeX Tables")
        lines.append("% Generated by chargraph2latex.py")
        lines.append("")
        lines.append(self.export_summary_statistics())
        lines.append("")
        lines.append(self.export_faction_network())
        lines.append("")
        lines.append(self.export_character_table())
        lines.append("")
        lines.append(self.export_schwartz_table())
        lines.append("")
        lines.append(self.export_trust_matrix())
        lines.append("")
        lines.append(self.export_relationship_table())
        
        filepath = os.path.join(self.output_dir, "character_graph_tables.tex")
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f"[OK] Exported combined tables to: {filepath}")
        except Exception as e:
            print(f"[ERROR] Failed to export combined tables: {e}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Convert character_graph.json to LaTeX tables',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python chargraph2latex.py
  python chargraph2latex.py --input character_graph.json --output ./tables
  python chargraph2latex.py --input world_sample/character_graph.json --output world_sample
  python chargraph2latex.py --combined  # Export all tables into one file
        """
    )
    parser.add_argument('--input', type=str, default='character_graph.json',
                        help='Path to character_graph.json (default: character_graph.json)')
    parser.add_argument('--output', type=str, default='.',
                        help='Output directory for LaTeX files (default: current directory)')
    parser.add_argument('--combined', action='store_true',
                        help='Export all tables into a single combined file')
    parser.add_argument('--list', action='store_true',
                        help='List available tables without exporting')
    
    args = parser.parse_args()
    
    print("="*70)
    print("CHARACTER GRAPH TO LATEX CONVERTER")
    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print("="*70)
    
    converter = CharGraphToLaTeX(args.input, args.output)
    
    if args.list:
        print("\nAvailable Tables:")
        print("  - character_properties.tex  : Character properties (faction, alignment, values)")
        print("  - schwartz_values.tex       : All 10 Schwartz values per character")
        print("  - relationships.tex         : Full relationship edges table")
        print("  - relationship_summary.tex  : Summary statistics (types, averages)")
        print("  - trust_matrix.tex          : Trust matrix between characters")
        print("  - faction_network.tex       : Faction network summary")
        return
    
    if args.combined:
        converter.export_combined()
    else:
        converter.export_all()


if __name__ == "__main__":
    main()