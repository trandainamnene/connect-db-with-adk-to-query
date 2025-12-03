from dotenv import dotenv_values
config = dotenv_values(".env") 

print(f"SELECT * FROM {config['TABLE']}")