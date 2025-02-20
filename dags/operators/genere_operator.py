import pandas as pd
import psycopg2
import os
from airflow.models import BaseOperator
from airflow.utils.decorators import apply_defaults
import configparser

class UserOccupationGenreAnalysisOperator(BaseOperator):
    """
    This operator performs user occupation and genre analysis on movie data.

    It reads user, movie, and rating data from CSV files specified in a configuration file,
    merges the datasets, categorizes users by age group, analyzes genre preferences
    based on occupation and age group, and saves the top 5 genres for each combination
    to a PostgreSQL table.
    """

    @apply_defaults
    def __init__(self, *args, **kwargs):
        """
        Initializes the UserOccupationGenreAnalysisOperator.

        Args:
            *args: Arguments passed to the BaseOperator constructor.
            **kwargs: Keyword arguments passed to the BaseOperator constructor.
        """
        super(UserOccupationGenreAnalysisOperator, self).__init__(*args, **kwargs)
        self.config = configparser.ConfigParser()
        CONFIG_PATH = os.getenv("CONFIG_PATH", "configs/")
        PATHS_CONFIG_PATH = os.path.join(CONFIG_PATH, 'paths_config.ini')
        self.config.read(PATHS_CONFIG_PATH)

    def save_to_postgres(self, table_name, df):
        """
        Saves a Pandas DataFrame to a PostgreSQL table with defined schema.

        This method establishes a connection to the PostgreSQL database using environment variables
        for credentials and connection details. It then checks for the existence of the table and
        creates it if necessary, defining the schema with columns for age group, occupation, and
        top genres as a text array. Finally, it iterates through the DataFrame and inserts each
        row into the table, converting the top genres list to a comma-separated string for storage.

        Args:
            table_name (str): Name of the table to save the data to.
            df (pd.DataFrame): The DataFrame containing the data to be saved.
        """
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost:5347"),
            user=os.getenv("POSTGRES_USER", "airflow"),
            password=os.getenv("POSTGRES_PASSWORD", "airflow"),
            database=os.getenv("POSTGRES_DATABASE", "airflow")
        )
        cursor = conn.cursor()

        # Create table schema if not exists
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id SERIAL PRIMARY KEY,
            age_group VARCHAR(255),
            occupation VARCHAR(255),
            top_genres TEXT[]
        )
        """)

        # Insert each row in the DataFrame
        for _, row in df.iterrows():
            genres_array = "{" + ", ".join(f'"{genre}"' for genre in row['top_genres']) + "}"
            cursor.execute(f"INSERT INTO {table_name} (age_group, occupation, top_genres) VALUES (%s, %s, %s)", 
                           (row['age_group'], row['occupation'], genres_array))

        conn.commit()
        cursor.close()
        conn.close()

    def execute(self, context):
        """
        Executes the user occupation and genre analysis logic.

        This method performs the following steps:

        1. Loads user, movie, and rating data from CSV files specified in the configuration file.
        2. Merges the datasets on user and item IDs.
        3. Defines age groups and categorizes users based on their age.
        4. Converts genre columns to numeric values (handling missing data).
        5. Groups data by age group and occupation, sums genres for each group, and finds the top 5 genres.
        6. Saves the results (top genres per age group and occupation) to a PostgreSQL table named 'top_genres'.
        """

        # Load and preprocess datasets
        ratings = pd.read_csv(self.config['Paths']['ratings_data_path'], sep='\t', names=['user_id', 'item_id', 'rating', 'timestamp'], encoding='ISO-8859-1', header=None)
        movies = pd.read_csv(self.config['Paths']['movies_data_path'], sep='|', encoding='ISO-8859-1', header=None,
                             names=['movie_id', 'movie_title', 'release_date', 'video_release_date', 'IMDb_URL', 
                                    'unknown', 'Action', 'Adventure', 'Animation', "Children's", 'Comedy', 
                                    'Crime', 'Documentary', 'Drama', 'Fantasy', 'Film-Noir', 'Horror', 
                                    'Musical', 'Mystery', 'Romance', 'Sci-Fi', 'Thriller', 'War', 'Western'])
        users = pd.read_csv(self.config['Paths']['user_data_path'], sep='|', encoding='ISO-8859-1', header=None,
                            names=['user_id', 'age', 'gender', 'occupation', 'zip_code'])

        # Merge datasets on user and item IDs
        merged_data = ratings.merge(movies[['movie_id', 'unknown', 'Action', 'Adventure', 'Animation', "Children's", 'Comedy', 
                                            'Crime', 'Documentary', 'Drama', 'Fantasy', 'Film-Noir', 'Horror', 
                                            'Musical', 'Mystery', 'Romance', 'Sci-Fi', 'Thriller', 'War', 'Western']],
                                    left_on='item_id', right_on='movie_id').merge(users[['user_id', 'age', 'occupation']],
                                                                                   on='user_id')

        # Define age groups and categorize
        age_bins = [0, 20, 25, 35, 45, float('inf')]
        age_labels = ["<20", "20-25", "25-35", "35-45", "45+"]
        merged_data['age_group'] = pd.cut(merged_data['age'], bins=age_bins, labels=age_labels, right=False)

        # Convert genre columns to numeric
        genre_columns = movies.columns[5:]
        merged_data[genre_columns] = merged_data[genre_columns].apply(pd.to_numeric, errors='coerce').fillna(0)

        # Group by age_group and occupation, sum genres, and find top 5 for each group
        genre_summary = merged_data.groupby(['age_group', 'occupation'], observed=False)[genre_columns].sum()
        top_genres_df = genre_summary.apply(lambda x: x.nlargest(5).index.tolist(), axis=1).reset_index(name='top_genres')

        # Save to PostgreSQL
        self.save_to_postgres("top_genres", top_genres_df)
        self.log.info("Successfully stored top genres in PostgreSQL 'top_genres' table.")