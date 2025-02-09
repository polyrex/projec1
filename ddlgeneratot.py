import re
from typing import Dict, List, Optional
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

@dataclass
class Column:
    name: str
    japanese_name: Optional[str]
    data_type: Optional[str] = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_generated: bool = False
    description: Optional[str] = None

@dataclass
class Table:
    name: str
    japanese_name: Optional[str]
    columns: List[Column]
    relationships: List['Relationship'] = None

@dataclass
class Relationship:
    from_table: str
    to_table: str
    type: str

class PumlToDDLConverter:
    def __init__(self):
        self.tables: Dict[str, Table] = {}
        self.relationships: List[Relationship] = []
        self.attributes: Dict[str, Dict] = {}
        self.combined_content: str = ""

    def combine_files(self, attributes_content: str, tables_content: str, er_content: str) -> str:
        """Combine the three files into a single PlantUML file in the correct order"""
        # Start with @startuml
        combined = "@startuml tables\n"
        
        # Add attributes definitions first (excluding @startuml and @enduml)
        attributes_content = self._clean_content(attributes_content)
        combined += attributes_content + "\n"
        
        # Add table definitions (excluding @startuml and @enduml)
        tables_content = self._clean_content(tables_content)
        combined += tables_content + "\n"
        
        # Add relationships from er.md (excluding @startuml and @enduml)
        er_content = self._clean_content(er_content)
        # Extract only the relationship lines
        for line in er_content.split('\n'):
            if '||-o{' in line or any(rel in line for rel in ['--', '--|>', 'o--o', '*--*']):
                combined += line + "\n"
        
        # End with @enduml
        combined += "@enduml"
        return combined

    def _clean_content(self, content: str) -> str:
        """Remove @startuml and @enduml tags and clean up the content"""
        content = re.sub(r'@startuml.*?\n', '', content)
        content = re.sub(r'@enduml', '', content)
        return content.strip()

    def parse_combined_content(self, content: str):
        """Parse the combined PlantUML content"""
        # First pass: Parse attributes
        attribute_pattern = r'!define\s+(\w+)\s+(\w+)\s+\[([^\]]+)\]\s+(\w+\(\d+\))(?:\s+/\'([^\']+)\'/?)?'
        for match in re.finditer(attribute_pattern, content):
            attr_name = match.group(1)
            column_code = match.group(2)
            japanese_name = match.group(3)
            data_type = match.group(4)
            description = match.group(5) if match.group(5) else None
            
            self.attributes[attr_name] = {
                'column_code': column_code,
                'japanese_name': japanese_name,
                'data_type': data_type,
                'description': description
            }

        # Second pass: Parse tables
        table_pattern = r'Table\((\w+),\s*"([^"]+)"\)[^{]*{([^}]+)}'
        for match in re.finditer(table_pattern, content):
            table_name = match.group(1)
            table_desc = match.group(2).split('\n')
            japanese_name = table_desc[1] if len(table_desc) > 1 else None
            
            columns = []
            column_content = match.group(3)
            for line in column_content.split('\n'):
                line = line.strip()
                if line == '--' or not line or line.startswith("'"):
                    continue
                
                is_primary_key = 'primary_key' in line
                is_foreign_key = 'foreign_key' in line
                is_generated = '<<generated>>' in line
                
                # Extract column name
                if is_primary_key:
                    col_match = re.search(r'primary_key\((\w+)\)', line)
                    col_name = col_match.group(1) if col_match else None
                elif is_foreign_key:
                    col_match = re.search(r'foreign_key\((\w+)\)', line)
                    col_name = col_match.group(1) if col_match else None
                else:
                    col_name = line.split()[0]
                
                # Look for attribute reference
                attr_ref = None
                bracket_match = re.search(r'\[(\w+)\]', line)
                if bracket_match:
                    attr_ref = bracket_match.group(1)
                
                # Get attribute details
                attr_details = self.attributes.get(attr_ref, {}) if attr_ref else {}
                
                # If the column name itself is an attribute name, use those details
                if col_name in self.attributes:
                    attr_details = self.attributes[col_name]
                
                columns.append(Column(
                    name=col_name,
                    japanese_name=attr_details.get('japanese_name'),
                    data_type=attr_details.get('data_type', 'VARCHAR(255)'),
                    is_primary_key=is_primary_key,
                    is_foreign_key=is_foreign_key,
                    is_generated=is_generated,
                    description=attr_details.get('description')
                ))
            
            self.tables[table_name] = Table(table_name, japanese_name, columns)

        # Third pass: Parse relationships
        for line in content.split('\n'):
            if '||-o{' in line:
                parts = line.strip().split()
                if len(parts) >= 3:
                    self.relationships.append(Relationship(
                        from_table=parts[0],
                        to_table=parts[2],
                        type=parts[1]
                    ))

    def generate_ddl(self) -> str:
        """Generate DDL statements from parsed information"""
        ddl = []
        
        # Create tables
        for table_name, table in self.tables.items():
            table_ddl = []
            if table.japanese_name:
                table_ddl.append(f"-- Table: {table_name} ({table.japanese_name})")
            table_ddl.append(f"CREATE TABLE {table_name} (")
            
            column_definitions = []
            primary_keys = []
            
            for column in table.columns:
                col_def = []
                col_def.append(f"    {column.name}")
                
                data_type = column.data_type if column.data_type else "VARCHAR(255)"
                col_def.append(data_type)
                
                if column.is_generated:
                    col_def.append("GENERATED ALWAYS AS IDENTITY")
                
                if column.japanese_name or column.description:
                    comments = []
                    if column.japanese_name:
                        comments.append(column.japanese_name)
                    if column.description:
                        comments.append(column.description)
                    col_def.append(f"-- {' | '.join(comments)}")
                
                if column.is_primary_key:
                    primary_keys.append(column.name)
                
                column_definitions.append(" ".join(col_def))
            
            if primary_keys:
                column_definitions.append(f"    CONSTRAINT pk_{table_name} PRIMARY KEY ({', '.join(primary_keys)})")
            
            table_ddl.append(",\n".join(column_definitions))
            table_ddl.append(");")
            
            
            ddl.append("\n".join(table_ddl))
        
        # Add foreign key constraints
        for relationship in self.relationships:
            from_table = self.tables.get(relationship.from_table)
            to_table = self.tables.get(relationship.to_table)
            
            if from_table and to_table:
                fk_columns = [col for col in to_table.columns if col.is_foreign_key]
                for fk_col in fk_columns:
                    ddl.append(f"""
ALTER TABLE {to_table.name}
    ADD CONSTRAINT fk_{to_table.name}_{from_table.name}
    FOREIGN KEY ({fk_col.name})
    REFERENCES {from_table.name} ({fk_col.name});""")
        
        return "\n\n".join(ddl)

def main():
    try:
        converter = PumlToDDLConverter()
        
        # Read all input files
        with open('attributes.pu', 'r', encoding='utf-8') as f:
            attributes_content = f.read()
        
        with open('tables.pu', 'r', encoding='utf-8') as f:
            tables_content = f.read()
        
        with open('er.md', 'r', encoding='utf-8') as f:
            er_content = f.read()
        
        # Combine files
        combined_content = converter.combine_files(attributes_content, tables_content, er_content)
        
        # Parse combined content
        converter.parse_combined_content(combined_content)
        
        # Generate DDL
        ddl = converter.generate_ddl()
        
        # Save to file
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        output_file = f"V{timestamp}__create_initial_schema.sql"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(ddl)
        
        print(f"DDL generated successfully in {output_file}")
        
        # Also save combined PlantUML file for reference
        with open('combined_model.puml', 'w', encoding='utf-8') as f:
            f.write(combined_content)
        
        print("Combined PlantUML file saved as combined_model.puml")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        print(traceback.format_exc())

if __name__ == "__main__":
    main()