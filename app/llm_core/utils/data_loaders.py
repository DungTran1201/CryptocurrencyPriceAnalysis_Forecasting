import os

import pandas as pd 

from config import (
    OperationLogger, 
    ExceptionLogger, 
    PerformanceLogger)

op_log = OperationLogger("DataLoader - OP")
ex_log = ExceptionLogger("DataLoader - EX") 
perf_log = PerformanceLogger("DataLoader -PE")

def load_history_csv(history_path: str) -> pd.DataFrame:
    """Load vocabulary CSV with error handling.
    
    Args:
        vocab_path: Path to Crypto data
    
    Returns:
        Pandas DataFrame with vocabulary data
    
    Raises:
        FileNotFoundError: If CSV file does not exist
        pd.errors.ParserError: If CSV parsing fails
    """
    if not os.path.exists(history_path):
        ex_log.handle(FileNotFoundError, f"{history_path} not found")
        raise FileNotFoundError
    
    try:
        df = pd.read_csv(history_path)
        
        op_log.info(f"{history_path} load successfuly")
        return df
    except pd.errors.ParserError as e:
        ex_log.handle(e, "Failed parse history path")
        raise e
