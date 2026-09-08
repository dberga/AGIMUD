#!/usr/bin/env python3
"""
Emotion Results to LaTeX Converter
Parses the output from swm_emotion.py and generates LaTeX tables
Uses emotion_tests.json for expected outcomes
"""

import re
import json
import os
import sys
from collections import Counter


class EmotionResultsToLaTeX:
    """Parse swm_emotion.py output and generate LaTeX tables"""
    
    def __init__(self, results_file: str = "results_emotion.txt", output_dir: str = ".", 
                 tests_file: str = "emotion_tests.json"):
        self.results_file = results_file
        self.output_dir = output_dir
        self.tests_file = tests_file
        self.content = ""
        self.configurations = []
        self.events = []
        self.appraisal_results = {}
        self.intensity_results = {}
        self.memory_results = {}
        self.sequence_results = {}
        self.action_tendency_results = {}
        self.expected_outcomes = {}
        self._load_tests()
        self._load_results()
    
    def _load_tests(self):
        """Load expected outcomes from emotion_tests.json"""
        if os.path.exists(self.tests_file):
            try:
                with open(self.tests_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.expected_outcomes = data.get('expected_outcomes', {})
                    print(f"[OK] Loaded expected outcomes from {self.tests_file}")
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
        
        # Parse the configuration name from the output
        config_match = re.search(r"Configuration: (\w+)", self.content)
        if config_match:
            self.configurations = [config_match.group(1)]
        else:
            self.configurations = ["default"]
        
        self._parse_appraisal_results()
        self._parse_intensity_results()
        self._parse_memory_results()
        self._parse_sequence_results()
        self._parse_action_tendency_results()
        
        print(f"[OK] Parsed results from {self.results_file}")
        print(f"  - Configuration: {self.configurations[0]}")
    
    def _parse_appraisal_results(self):
        """Parse TEST 1: Emotion Appraisal from Events"""
        pattern = r"TEST 1: Emotion Appraisal from Events.*?\n(.*?)(?=\n\n|\n-{70}|\Z)"
        match = re.search(pattern, self.content, re.DOTALL)
        if not match:
            print("[WARNING] Could not find appraisal results")
            return
        
        lines = match.group(1).strip().split('\n')
        for line in lines:
            if not line.strip():
                continue
            # Match: [OK] Event: 'goal_blocked' -> Emotion: anger (Intensity: 0.60)
            event_match = re.search(r"Event: '([^']+)'", line)
            emotion_match = re.search(r"Emotion: (\w+)", line)
            intensity_match = re.search(r"Intensity: ([\d.]+)", line)
            
            if event_match and emotion_match and intensity_match:
                event = event_match.group(1)
                emotion = emotion_match.group(1)
                intensity = float(intensity_match.group(1))
                self.appraisal_results[event] = {
                    "emotion": emotion,
                    "intensity": intensity
                }
                self.events.append(event)
    
    def _parse_intensity_results(self):
        """Parse TEST 2: Intensity Modulation by Status Variables"""
        pattern = r"TEST 2: Intensity Modulation by Status Variables.*?\n(.*?)(?=\n\n|\n-{70}|\Z)"
        match = re.search(pattern, self.content, re.DOTALL)
        if not match:
            print("[WARNING] Could not find intensity results")
            return
        
        lines = match.group(1).strip().split('\n')
        for line in lines:
            if not line.strip() or 'Status:' not in line:
                continue
            # Match: Status: low_health_low_stamina | Health: 20 | Stamina: 20 -> anger (Intensity: 0.85)
            label_match = re.search(r"Status: (\w+)", line)
            health_match = re.search(r"Health: (\d+)", line)
            stamina_match = re.search(r"Stamina: (\d+)", line)
            intensity_match = re.search(r"Intensity: ([\d.]+)", line)
            
            if label_match and health_match and stamina_match and intensity_match:
                label = label_match.group(1)
                health = int(health_match.group(1))
                stamina = int(stamina_match.group(1))
                intensity = float(intensity_match.group(1))
                self.intensity_results[label] = {
                    "health": health,
                    "stamina": stamina,
                    "intensity": intensity
                }
    
    def _parse_memory_results(self):
        """Parse TEST 3: Emotional Memory Sequence"""
        pattern = r"TEST 3: Emotional Memory Sequence.*?\n(.*?)(?=\n\n|\n-{70}|\Z)"
        match = re.search(pattern, self.content, re.DOTALL)
        if not match:
            print("[WARNING] Could not find memory results")
            return
        
        lines = match.group(1).strip().split('\n')
        step = 1
        for line in lines:
            if not line.strip():
                continue
            if 'Step | Event' in line or '-----' in line:
                continue
            # Match: 1  | goal_blocked             | anger      | 0.60
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 4:
                event = parts[1].strip()
                emotion = parts[2].strip()
                try:
                    intensity = float(parts[3].strip())
                    self.memory_results[step] = {
                        "event": event,
                        "emotion": emotion,
                        "intensity": intensity
                    }
                    step += 1
                except ValueError:
                    continue
    
    def _parse_sequence_results(self):
        """Parse TEST 5: Emotion Sequence Over Time"""
        pattern = r"TEST 5: Emotion Sequence Over Time.*?\n(.*?)(?=\n\n|\n-{70}|\Z)"
        match = re.search(pattern, self.content, re.DOTALL)
        if not match:
            print("[WARNING] Could not find sequence results")
            return
        
        lines = match.group(1).strip().split('\n')
        for line in lines:
            if not line.strip():
                continue
            if 'Step | Event' in line or '-----' in line:
                continue
            # Match: 1  | goal_blocked             | anger      | 0.60
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 4:
                step = int(parts[0])
                event = parts[1].strip()
                emotion = parts[2].strip()
                try:
                    intensity = float(parts[3].strip())
                    self.sequence_results[step] = {
                        "event": event,
                        "emotion": emotion,
                        "intensity": intensity
                    }
                except ValueError:
                    continue
    
    def _parse_action_tendency_results(self):
        """Parse TEST 4: Emotion-to-Action Tendency Mapping"""
        pattern = r"TEST 4: Emotion-to-Action Tendency Mapping.*?\n(.*?)(?=\n\n|\n-{70}|\Z)"
        match = re.search(pattern, self.content, re.DOTALL)
        if not match:
            print("[WARNING] Could not find action tendency results")
            return
        
        lines = match.group(1).strip().split('\n')
        for line in lines:
            if not line.strip():
                continue
            # Match: anger      -> combat     (Arousal: high)
            emotion_match = re.search(r'(\w+)\s+->\s+(\w+)\s+\(Arousal:\s+(\w+)\)', line)
            if emotion_match:
                emotion = emotion_match.group(1)
                tendency = emotion_match.group(2)
                arousal = emotion_match.group(3)
                self.action_tendency_results[emotion] = {
                    "tendency": tendency,
                    "arousal": arousal
                }
    
    def export_appraisal_table(self) -> str:
        """Export emotion appraisal results table"""
        lines = []
        lines.append("% Emotion Appraisal Results")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Emotion Appraisal from Events}")
        lines.append("\\label{tab:emotion_appraisal}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|l|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Event Type} & \\textbf{Mapped Emotion} & \\textbf{Intensity} \\\\")
        lines.append("\\hline")
        
        for event, data in self.appraisal_results.items():
            emotion = data.get("emotion", "N/A")
            intensity = data.get("intensity", 0.0)
            lines.append(f"\\texttt{{{event}}} & {emotion} & {intensity:.2f} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_intensity_table(self) -> str:
        """Export intensity modulation results table"""
        lines = []
        lines.append("% Intensity Modulation Results")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Intensity Modulation by Status Variables}")
        lines.append("\\label{tab:intensity_modulation}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|l|c|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Status Condition} & \\textbf{Health} & \\textbf{Stamina} & \\textbf{Intensity} \\\\")
        lines.append("\\hline")
        
        for label, data in self.intensity_results.items():
            health = data.get("health", 0)
            stamina = data.get("stamina", 0)
            intensity = data.get("intensity", 0.0)
            display_label = label.replace("_", " ").title()
            lines.append(f"{display_label} & {health} & {stamina} & {intensity:.2f} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_memory_table(self) -> str:
        """Export emotional memory sequence table"""
        lines = []
        lines.append("% Emotional Memory Sequence")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Emotional Memory Sequence}")
        lines.append("\\label{tab:memory_sequence}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|c|l|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Step} & \\textbf{Event} & \\textbf{Emotion} & \\textbf{Intensity} \\\\")
        lines.append("\\hline")
        
        for step, data in sorted(self.memory_results.items()):
            event = data.get("event", "N/A")
            emotion = data.get("emotion", "N/A")
            intensity = data.get("intensity", 0.0)
            lines.append(f"{step} & \\texttt{{{event}}} & {emotion} & {intensity:.2f} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_sequence_table(self) -> str:
        """Export emotion sequence over time table"""
        lines = []
        lines.append("% Emotion Sequence Over Time")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Emotion Sequence Over Time}")
        lines.append("\\label{tab:sequence_over_time}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|c|l|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Step} & \\textbf{Event} & \\textbf{Emotion} & \\textbf{Intensity} \\\\")
        lines.append("\\hline")
        
        for step, data in sorted(self.sequence_results.items()):
            event = data.get("event", "N/A")
            emotion = data.get("emotion", "N/A")
            intensity = data.get("intensity", 0.0)
            lines.append(f"{step} & \\texttt{{{event}}} & {emotion} & {intensity:.2f} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_action_tendency_table(self) -> str:
        """Export emotion-to-action tendency mapping table"""
        lines = []
        lines.append("% Emotion-to-Action Tendency Mapping")
        lines.append("\\begin{table}[htbp]")
        lines.append("\\centering")
        lines.append("\\caption{Emotion-to-Action Tendency Mapping}")
        lines.append("\\label{tab:action_tendency}")
        lines.append("\\begin{adjustbox}{width=\\columnwidth}")
        lines.append("\\begin{tabular}{|l|c|c|}")
        lines.append("\\hline")
        lines.append("\\textbf{Emotion} & \\textbf{Action Tendency} & \\textbf{Arousal} \\\\")
        lines.append("\\hline")
        
        for emotion, data in self.action_tendency_results.items():
            tendency = data.get("tendency", "idle")
            arousal = data.get("arousal", "medium")
            lines.append(f"{emotion.title()} & {tendency.title()} & {arousal.title()} \\\\")
        
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{adjustbox}")
        lines.append("\\end{table}")
        
        return '\n'.join(lines)
    
    def export_combined_appraisal_table(self) -> str:
        """Export combined appraisal results across multiple configurations if available"""
        # This would need multiple configs to be parsed
        # Currently only supports single config
        return self.export_appraisal_table()
    
    def export_all(self):
        """Export all tables to individual LaTeX files"""
        tables = {
            "appraisal_results.tex": self.export_appraisal_table(),
            "intensity_modulation.tex": self.export_intensity_table(),
            "memory_sequence.tex": self.export_memory_table(),
            "sequence_over_time.tex": self.export_sequence_table(),
            "action_tendency.tex": self.export_action_tendency_table(),
        }
        
        print("\n" + "="*70)
        print("EXPORTING EMOTION LATEX TABLES")
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
        lines.append("% Emotion Results LaTeX Tables")
        lines.append("% Generated from " + self.results_file)
        lines.append("% Expected outcomes from " + self.tests_file)
        lines.append("")
        lines.append(self.export_appraisal_table())
        lines.append("")
        lines.append(self.export_intensity_table())
        lines.append("")
        lines.append(self.export_memory_table())
        lines.append("")
        lines.append(self.export_sequence_table())
        lines.append("")
        lines.append(self.export_action_tendency_table())
        
        filepath = os.path.join(self.output_dir, "emotion_tables.tex")
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f"[OK] Exported combined tables to: {filepath}")
        except Exception as e:
            print(f"[ERROR] Failed to export combined tables: {e}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Convert swm_emotion.py results to LaTeX tables',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python emotiontxt2latex.py
  python emotiontxt2latex.py --input results_emotion.txt --output ./tables
  python emotiontxt2latex.py --tests emotion_tests.json --combined
        """
    )
    parser.add_argument('--input', '-i', type=str, default='results_emotion.txt',
                        help='Path to results_emotion.txt (default: results_emotion.txt)')
    parser.add_argument('--output', '-o', type=str, default='.',
                        help='Output directory for LaTeX files (default: current directory)')
    parser.add_argument('--tests', '-t', type=str, default='emotion_tests.json',
                        help='Path to emotion_tests.json (default: emotion_tests.json)')
    parser.add_argument('--combined', '-c', action='store_true',
                        help='Export all tables into a single combined file')
    parser.add_argument('--list', '-l', action='store_true',
                        help='List available tables without exporting')
    
    args = parser.parse_args()
    
    print("="*70)
    print("EMOTION RESULTS TO LATEX CONVERTER")
    print(f"Input: {args.input}")
    print(f"Tests: {args.tests}")
    print(f"Output: {args.output}")
    print("="*70)
    
    converter = EmotionResultsToLaTeX(args.input, args.output, args.tests)
    
    if args.list:
        print("\nAvailable Tables:")
        print("  - appraisal_results.tex      : Emotion appraisal from events")
        print("  - intensity_modulation.tex   : Intensity modulation by status")
        print("  - memory_sequence.tex        : Emotional memory sequence")
        print("  - sequence_over_time.tex     : Emotion sequence over time")
        print("  - action_tendency.tex        : Emotion-to-action tendency mapping")
        return
    
    if args.combined:
        converter.export_combined()
    else:
        converter.export_all()


if __name__ == "__main__":
    main()