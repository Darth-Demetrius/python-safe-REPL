"""Purely syntactic definitions of AST node sets, organized by semantics and grammar level."""
import ast

__all__ = [
    "LITERALS",
    "OPERATORS",
    "EXPRESSIONS_L1",
    "EXP_SUBSCRIPTING",
    "EXP_COMPREHENSIONS",

    "CONTROL_FLOW_STMT",
    "FUNCTION_AND_CLASS_DEFS",

    "STATEMENT_IMPORTS",
    "PATTERN_MATCHING",
    "ASYNC_AND_AWAIT",
    "PATTERN",
    "TYPE_PARAM",
]

SET = set[type[ast.AST]]

## Node classes ##
# These are organized by type.
ROOT_NODES: SET = {ast.mod}  # Level 1  # MOD

LITERALS: SET = {
    ast.Constant,        # Level 1
    ast.FormattedValue,  # Level 1
    ast.JoinedStr,       # Level 1
    ast.TemplateStr,     # Level 1
    ast.Interpolation,   # Level 1
    ast.List,            # Level 1
    ast.Tuple,           # Level 1
    ast.Set,             # Level 1
    ast.Dict,            # Level 1
}

VARIABLES: SET = {
    ast.Name,          # Level 1
    ast.expr_context,  # Level 1/2  # EXPR_CONTEXT
    ast.Starred,       # Level 2
}

# EXPRESSIONS
OPERATORS: SET = {
    ast.BinOp,     # Level 1
    ast.BoolOp,    # Level 1
    ast.boolop,    # Level 1  # BOOLOP
    ast.Compare,   # Level 1
    ast.cmpop,     # Level 1  # CMPOP
    ast.operator,  # Level 1  # OPERATOR
    ast.UnaryOp,   # Level 1
    ast.unaryop,   # Level 1  # UNARYOP
}
EXPRESSIONS_L1: SET = {
    ast.Call,       # Level 1
    ast.IfExp,      # Level 1
    ast.Attribute,  # Level 1
    ast.Expr,     # Level 1
    ast.keyword,  # Level 1
}
EXPRESSIONS: SET = {
    *OPERATORS,
    *EXPRESSIONS_L1,
    ast.NamedExpr,  # Level 3
}

EXP_SUBSCRIPTING: SET = {
    ast.Subscript,  # Level 1
    ast.Slice,      # Level 1
}

EXP_COMPREHENSIONS: SET = {
    ast.ListComp,       # Level 1
    ast.SetComp,        # Level 1
    ast.GeneratorExp,   # Level 1
    ast.DictComp,       # Level 1
    ast.comprehension,  # Level 1
}

# STATEMENTS
STATEMENTS: SET = {
    ast.Assign,     # Level 1
    ast.AnnAssign,  # Level 3
    ast.AugAssign,  # Level 1
    ast.Raise,      # Level 2
    ast.Assert,     # Level 1
    ast.Delete,     # Level 2
    ast.Pass,       # Level 1
    ast.TypeAlias,  # Level 3
}
STATEMENT_IMPORTS: SET = {
    ast.Import,      # Level 3
    ast.ImportFrom,  # Level 3
    ast.alias,       # Level 3
}

# CONTROL_FLOW
CONTROL_FLOW_STMT: SET = {
    ast.For,            # Level 2
    ast.While,          # Level 2
    ast.Break,          # Level 2
    ast.Try,            # Level 2
    ast.With,           # Level 2
}
CONTROL_FLOW: SET = {
    ast.If,             # Level 1
    *CONTROL_FLOW_STMT,
    ast.ExceptHandler,  # Level 2  # EXEPTHANDLER
    ast.withitem,       # Level 2
    ast.TryStar,        # Level 3
}

PATTERN_MATCHING: SET = {
    ast.Match,       # Level 3
    ast.match_case,  # Level 3
    ast.pattern,     # Level 3  # PATTERN
}

TYPE_ANNOTATIONS: SET = {ast.TypeIgnore}  # Level 3  # TYPE_IGNORE

TYPE_PARAMETERS: SET = {ast.type_param}   # Level 3  # TYPE_PARAM

# FUNCTION_AND_CLASS_DEFS
FUNC_CLASS_DEFS_STMT: SET = {
    ast.FunctionDef,  # Level 2
    ast.ClassDef,     # Level 2
    ast.Return,       # Level 2
    ast.Global,       # Level 2
    ast.Nonlocal,     # Level 2
}
FUNC_CLASS_DEFS_EXPR: SET = {
    ast.Lambda,     # Level 2
    ast.Yield,      # Level 3
    ast.YieldFrom,  # Level 3
}
FUNCTION_AND_CLASS_DEFS: SET = {
    *FUNC_CLASS_DEFS_STMT,
    *FUNC_CLASS_DEFS_EXPR,
    ast.arguments,  # Level 2
    ast.arg,        # Level 2
}

# ASYNC_AND_AWAIT
ASYNC_STMT: SET = {
    ast.AsyncFunctionDef,  # Level 3
    ast.AsyncFor,          # Level 3
    ast.AsyncWith,         # Level 3
}
ASYNC_AND_AWAIT: SET = {
    *ASYNC_STMT,
    ast.Await,  # Level 3
}


## Abstract grammar ##
# These are representatives of the internal AST grammar, purely for reference.
# The lowercase of the names are valid AST nodes themselves which hold the listed nodes.
# i.e. ast.boolop == ast.And | ast.Or
# After testing, it can be finicky
MOD: SET = {
    ast.Module,       # Level 1
    ast.Interactive,  # Level 1
    ast.Expression,   # Level 1
    ast.FunctionType, # Level 3
}
STMT: SET = {
    *FUNC_CLASS_DEFS_STMT,
    *ASYNC_STMT,

    *STATEMENTS,

    *CONTROL_FLOW_STMT,

    ast.Match,           # Level 3

    *{ast.Import,        # Level 3
        ast.ImportFrom,  # Level 3
    },  # STATEMENT_IMPORTS

    ast.Expr,      # Level 1
    ast.Continue,  # Level 2
}
EXPR: SET = {
    *EXPRESSIONS_L1,
    ast.BoolOp,     # Level 1
    ast.NamedExpr,  # Level 3
    ast.BinOp,      # Level 1
    ast.UnaryOp,    # Level 1
    *FUNC_CLASS_DEFS_EXPR,
    *(EXP_COMPREHENSIONS - {ast.comprehension}),  # Level 1
    ast.Await,      # Level 3
    ast.Compare,    # Level 1
    *LITERALS,

    *{ast.Name,     # Level 1
        ast.Starred,  # Level 2
    },  # VARIABLES

    *EXP_SUBSCRIPTING,
}

EXPR_CONTEXT: SET = {
    ast.Load,   # Level 1
    ast.Store,  # Level 1
    ast.Del,    # Level 2
}
BOOLOP: SET = {ast.And, ast.Or}  # Level 1
OPERATOR: SET = {
    ast.Add,       # Level 1
    ast.Sub,       # Level 1
    ast.Mult,      # Level 1
    ast.MatMult,   # Level 1
    ast.Div,       # Level 1
    ast.Mod,       # Level 1
    ast.Pow,       # Level 1
    ast.LShift,    # Level 1
    ast.RShift,    # Level 1
    ast.BitOr,     # Level 1
    ast.BitXor,    # Level 1
    ast.BitAnd,    # Level 1
    ast.FloorDiv,  # Level 1
}
UNARYOP: SET = {
    ast.Invert,  # Level 1
    ast.Not,     # Level 1
    ast.UAdd,    # Level 1
    ast.USub,    # Level 1
}
CMPOP: SET = {
    ast.Eq,     # Level 1
    ast.NotEq,  # Level 1
    ast.Lt,     # Level 1
    ast.LtE,    # Level 1
    ast.Gt,     # Level 1
    ast.GtE,    # Level 1
    ast.Is,     # Level 1
    ast.IsNot,  # Level 1
    ast.In,     # Level 1
    ast.NotIn,  # Level 1
}
EXEPTHANDLER: SET = {ast.ExceptHandler}  # Level 2
PATTERN: SET = {
    ast.MatchValue,      # Level 3
    ast.MatchSingleton,  # Level 3
    ast.MatchSequence,   # Level 3
    ast.MatchMapping,    # Level 3
    ast.MatchClass,      # Level 3

    ast.MatchStar,       # Level 3

    ast.MatchAs,         # Level 3
    ast.MatchOr,         # Level 3
}
TYPE_IGNORE: SET = {ast.TypeIgnore}  # Level 3
TYPE_PARAM: SET = {
    ast.TypeVar,       # Level 3
    ast.ParamSpec,     # Level 3
    ast.TypeVarTuple,  # Level 3
}
