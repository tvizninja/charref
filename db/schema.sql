PRAGMA foreign_keys = ON;

CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE source (
  id INTEGER PRIMARY KEY,
  source_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  publisher TEXT,
  version TEXT,
  published_at TEXT,
  retrieved_at TEXT,
  url TEXT,
  license TEXT,
  notes TEXT
);

CREATE TABLE unicode_block (
  id INTEGER PRIMARY KEY,
  block_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  first_cp INTEGER NOT NULL,
  last_cp INTEGER NOT NULL,
  source_id INTEGER REFERENCES source(id)
);

CREATE TABLE unicode_script (
  id INTEGER PRIMARY KEY,
  script_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  source_id INTEGER REFERENCES source(id)
);

CREATE TABLE unicode_codepoint (
  cp INTEGER PRIMARY KEY CHECK(cp BETWEEN 0 AND 1114111),
  name TEXT,
  age TEXT,
  general_category TEXT,
  canonical_combining_class INTEGER,
  bidi_class TEXT,
  decomposition TEXT,
  numeric_type TEXT,
  numeric_value TEXT,
  mirrored INTEGER NOT NULL DEFAULT 0,
  east_asian_width TEXT,
  block_id INTEGER REFERENCES unicode_block(id),
  primary_script_id INTEGER REFERENCES unicode_script(id),
  source_id INTEGER REFERENCES source(id)
);

CREATE TABLE unicode_property (
  cp INTEGER NOT NULL REFERENCES unicode_codepoint(cp),
  property TEXT NOT NULL,
  value TEXT NOT NULL,
  source_id INTEGER REFERENCES source(id),
  PRIMARY KEY(cp, property, value)
);

CREATE TABLE code_system (
  id INTEGER PRIMARY KEY,
  system_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  system_type TEXT NOT NULL,
  standard_ref TEXT,
  source_id INTEGER REFERENCES source(id),
  notes TEXT
);

CREATE TABLE code_position (
  id INTEGER PRIMARY KEY,
  system_id INTEGER NOT NULL REFERENCES code_system(id),
  position_key TEXT NOT NULL,
  plane INTEGER,
  row_no INTEGER,
  cell_no INTEGER,
  byte_value BLOB,
  numeric_value INTEGER,
  source_id INTEGER REFERENCES source(id),
  notes TEXT,
  UNIQUE(system_id, position_key)
);

CREATE TABLE mapping (
  id INTEGER PRIMARY KEY,
  code_position_id INTEGER NOT NULL REFERENCES code_position(id),
  direction TEXT NOT NULL CHECK(direction IN ('decode','encode','both')),
  mapping_kind TEXT NOT NULL DEFAULT 'standard',
  priority INTEGER NOT NULL DEFAULT 0,
  source_id INTEGER REFERENCES source(id),
  notes TEXT
);

CREATE TABLE mapping_unicode (
  mapping_id INTEGER NOT NULL REFERENCES mapping(id) ON DELETE CASCADE,
  seq_index INTEGER NOT NULL,
  cp INTEGER NOT NULL REFERENCES unicode_codepoint(cp),
  PRIMARY KEY(mapping_id, seq_index)
);

CREATE TABLE collection (
  id INTEGER PRIMARY KEY,
  collection_key TEXT NOT NULL UNIQUE,
  parent_id INTEGER REFERENCES collection(id),
  title TEXT NOT NULL,
  short_title TEXT,
  collection_type TEXT NOT NULL,
  description TEXT,
  source_id INTEGER REFERENCES source(id),
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE collection_member_unicode (
  collection_id INTEGER NOT NULL REFERENCES collection(id),
  cp INTEGER NOT NULL REFERENCES unicode_codepoint(cp),
  sort_order INTEGER,
  notes TEXT,
  PRIMARY KEY(collection_id, cp)
);

CREATE TABLE collection_member_position (
  collection_id INTEGER NOT NULL REFERENCES collection(id),
  code_position_id INTEGER NOT NULL REFERENCES code_position(id),
  sort_order INTEGER,
  notes TEXT,
  PRIMARY KEY(collection_id, code_position_id)
);

CREATE TABLE issue (
  id INTEGER PRIMARY KEY,
  issue_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  severity TEXT,
  description TEXT,
  source_id INTEGER REFERENCES source(id)
);

CREATE TABLE unicode_issue (
  cp INTEGER NOT NULL REFERENCES unicode_codepoint(cp),
  issue_id INTEGER NOT NULL REFERENCES issue(id),
  notes TEXT,
  PRIMARY KEY(cp, issue_id)
);

CREATE TABLE position_issue (
  code_position_id INTEGER NOT NULL REFERENCES code_position(id),
  issue_id INTEGER NOT NULL REFERENCES issue(id),
  notes TEXT,
  PRIMARY KEY(code_position_id, issue_id)
);


CREATE TABLE unicode_sequence (
  id INTEGER PRIMARY KEY,
  sequence_key TEXT NOT NULL UNIQUE,
  sequence_type TEXT NOT NULL,
  name TEXT,
  source_id INTEGER REFERENCES source(id),
  notes TEXT
);

CREATE TABLE unicode_sequence_member (
  sequence_id INTEGER NOT NULL REFERENCES unicode_sequence(id) ON DELETE CASCADE,
  seq_index INTEGER NOT NULL,
  cp INTEGER NOT NULL REFERENCES unicode_codepoint(cp),
  PRIMARY KEY(sequence_id, seq_index)
);

CREATE TABLE unicode_sequence_annotation (
  sequence_id INTEGER NOT NULL REFERENCES unicode_sequence(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY(sequence_id, key)
);

CREATE TABLE collection_member_sequence (
  collection_id INTEGER NOT NULL REFERENCES collection(id),
  sequence_id INTEGER NOT NULL REFERENCES unicode_sequence(id),
  sort_order INTEGER,
  notes TEXT,
  PRIMARY KEY(collection_id, sequence_id)
);

CREATE TABLE variation_collection (
  id INTEGER PRIMARY KEY,
  collection_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  version TEXT,
  source_id INTEGER REFERENCES source(id)
);

CREATE TABLE variation_sequence (
  id INTEGER PRIMARY KEY,
  base_cp INTEGER NOT NULL REFERENCES unicode_codepoint(cp),
  variation_cp INTEGER NOT NULL REFERENCES unicode_codepoint(cp),
  collection_id INTEGER NOT NULL REFERENCES variation_collection(id),
  identifier TEXT,
  source_id INTEGER REFERENCES source(id),
  UNIQUE(base_cp, variation_cp, collection_id)
);

CREATE TABLE variation_annotation (
  variation_id INTEGER NOT NULL REFERENCES variation_sequence(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY(variation_id, key)
);

CREATE TABLE relation (
  id INTEGER PRIMARY KEY,
  from_cp INTEGER NOT NULL REFERENCES unicode_codepoint(cp),
  to_cp INTEGER NOT NULL REFERENCES unicode_codepoint(cp),
  relation_type TEXT NOT NULL,
  source_id INTEGER REFERENCES source(id),
  notes TEXT,
  UNIQUE(from_cp, to_cp, relation_type)
);

CREATE INDEX idx_unicode_name ON unicode_codepoint(name);
CREATE INDEX idx_mapping_cp ON mapping_unicode(cp);
CREATE INDEX idx_code_position_numeric ON code_position(system_id, numeric_value);
CREATE INDEX idx_collection_parent ON collection(parent_id, sort_order);
CREATE INDEX idx_relation_from ON relation(from_cp, relation_type);
CREATE INDEX idx_relation_to ON relation(to_cp, relation_type);
CREATE INDEX idx_unicode_sequence_type ON unicode_sequence(sequence_type);
