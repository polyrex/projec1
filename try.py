import re
import hashlib
import json
import argparse
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

class SQLDialect(Enum):
    POSTGRESQL = "postgresql"
    ORACLE = "oracle"

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
    def __init__(self, dialect: SQLDialect = SQLDialect.POSTGRESQL):
        self.tables: Dict[str, Table] = {}
        self.relationships: List[Relationship] = []
        self.attributes: Dict[str, Dict] = {}
        self.combined_content: str = ""
        self.version_file = Path("schema_version.json")
        self.dialect = dialect

    def calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file content"""
        with open(file_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()

    def load_version_info(self) -> Dict:
        """Load version information from version file"""
        if self.version_file.exists():
            with open(self.version_file, 'r') as f:
                return json.load(f)
        return {
            'last_version': 0,
            'file_hashes': {},
            'last_generated': None
        }

    def save_version_info(self, version_info: Dict):
        """Save version information to version file"""
        with open(self.version_file, 'w') as f:
            json.dump(version_info, f, indent=2)

    def files_have_changed(self, files: List[str]) -> bool:
        """Check if any of the input files have changed since last generation"""
        version_info = self.load_version_info()
        old_hashes = version_info.get('file_hashes', {})
        
        for file_path in files:
            current_hash = self.calculate_file_hash(file_path)
            if old_hashes.get(file_path) != current_hash:
                return True
        return False

    def update_version_info(self, files: List[str], new_version: int):
        """Update version information with new file hashes and version number"""
        version_info = self.load_version_info()
        version_info['last_version'] = new_version
        version_info['last_generated'] = datetime.now().isoformat()
        version_info['file_hashes'] = {
            file_path: self.calculate_file_hash(file_path)
            for file_path in files
        }
        self.save_version_info(version_info)

    def get_next_version(self) -> int:
        """Get the next version number"""
        version_info = self.load_version_info()
        return version_info.get('last_version', 0) + 1

    def convert_data_type(self, pg_type: str) -> str:
        """Convert PostgreSQL data type to Oracle data type if needed"""
        if self.dialect == SQLDialect.POSTGRESQL:
            return pg_type

        # PostgreSQL to Oracle type mapping
        type_mapping = {
            'SERIAL': 'NUMBER GENERATED ALWAYS AS IDENTITY',
            'BIGSERIAL': 'NUMBER GENERATED ALWAYS AS IDENTITY',
            'VARCHAR': 'VARCHAR2',
            'TEXT': 'CLOB',
            'BOOLEAN': 'NUMBER(1)',
            'TIMESTAMP': 'TIMESTAMP',
            'JSONB': 'CLOB',
            'UUID': 'VARCHAR2(36)',
            'BYTEA': 'BLOB',
        }

        # Extract base type and size/precision if present
        match = re.match(r'(\w+)(?:\(([^)]+)\))?', pg_type)
        if not match:
            return pg_type

        base_type = match.group(1).upper()
        size_info = match.group(2)

        # Convert the type
        oracle_type = type_mapping.get(base_type, base_type)
        if size_info and oracle_type != 'CLOB' and oracle_type != 'BLOB':
            return f"{oracle_type}({size_info})"
        return oracle_type

    def get_identity_syntax(self) -> str:
        """Get the appropriate identity column syntax for the selected dialect"""
        if self.dialect == SQLDialect.POSTGRESQL:
            return "GENERATED ALWAYS AS IDENTITY"
        return "GENERATED ALWAYS AS IDENTITY"  # Oracle uses the same syntax

    def combine_files(self, attributes_content: str, tables_content: str, er_content: str) -> str:
        """Combine the three files into a single PlantUML file in the correct order"""
        combined = "@startuml tables\n"
        
        # Add attributes definitions
        attributes_content = self._clean_content(attributes_content)
        combined += attributes_content + "\n"
        
        # Add table definitions
        tables_content = self._clean_content(tables_content)
        combined += tables_content + "\n"
        
        # Add relationships from er.md
        er_content = self._clean_content(er_content)
        
        # Process each line from er.md, excluding !include lines
        for line in er_content.split('\n'):
            if not line.strip().startswith('!include'):
                combined += line + "\n"
            
       
        
        combined += "@enduml"
        return combined

    def _clean_content(self, content: str) -> str:
        """Remove @startuml and @enduml tags and clean up the content"""
        content = re.sub(r'@startuml.*?\n', '', content)
        content = re.sub(r'@enduml', '', content)
        return content.strip()

    def parse_combined_content(self, content: str):
        """Parse the combined PlantUML content"""
        # Parse attributes
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

        # Parse tables
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

        # Parse relationships
        for line in content.split('\n'):
            if any(rel in line for rel in ['||-o{', '--|>', '--', 'o--o', '*--*']):
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
            
            # Add table comment
            if self.dialect == SQLDialect.ORACLE and table.japanese_name:
                table_ddl.append(f"COMMENT ON TABLE {table_name} IS '{table.japanese_name}';")
            else:
                if table.japanese_name:
                    table_ddl.append(f"-- Table: {table_name} ({table.japanese_name})")
            
            table_ddl.append(f"CREATE TABLE {table_name} (")
            
            column_definitions = []
            primary_keys = []
            
            for column in table.columns:
                col_def = []
                col_def.append(f"    {column.name}")
                
                data_type = self.convert_data_type(column.data_type if column.data_type else "VARCHAR(255)")
                col_def.append(data_type)
                
                if column.is_generated:
                    col_def.append(self.get_identity_syntax())
                
                if self.dialect == SQLDialect.POSTGRESQL:
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
            
            # Add column comments for Oracle
            if self.dialect == SQLDialect.ORACLE:
                for column in table.columns:
                    if column.japanese_name or column.description:
                        comments = []
                        if column.japanese_name:
                            comments.append(column.japanese_name)
                        if column.description:
                            comments.append(column.description)
                        comment_text = ' | '.join(comments)
                        table_ddl.append(f"COMMENT ON COLUMN {table_name}.{column.name} IS '{comment_text}';")
            
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
        # Add argument parsing for dialect selection
        import argparse
        parser = argparse.ArgumentParser(description='Convert PUML to DDL')
        parser.add_argument('--dialect', choices=['postgresql', 'oracle'], 
                          default='postgresql', help='SQL dialect to use')
        args = parser.parse_args()

        # Create converter with selected dialect
        dialect = SQLDialect(args.dialect)
        converter = PumlToDDLConverter(dialect=dialect)
        input_files = ['attributes.pu', 'tables.pu', 'er.md']
        
        # Check if files have changed
        if not converter.files_have_changed(input_files):
            print("No changes detected in input files. Skipping DDL generation.")
            return
        
        # Get next version number
        next_version = converter.get_next_version()
        
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
        
        # Save to file with version number and dialect
        version_str = str(next_version).zfill(4)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        output_file = f"V{version_str}__{timestamp}__create_schema_{args.dialect}.sql"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(ddl)
        
        # Update version information
        converter.update_version_info(input_files, next_version)
        
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