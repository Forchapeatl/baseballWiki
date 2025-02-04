from flask import Flask, render_template, request, jsonify
from google.cloud import bigquery
import os, io
import requests
import numpy as np
from google.cloud import aiplatform
from langchain_google_vertexai import VertexAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.chains import ConversationalRetrievalChain
from langchain_google_vertexai import ChatVertexAI
from google.cloud import translate_v2 as translate  # Google Translate API for translation
from flask_babel import Babel, _


# Initialize Flask app
app = Flask(__name__)
babel = Babel()


app.config['BABEL_DEFAULT_LOCALE'] = 'en'

def get_locale():
    # Check the lang query parameter
    lang = request.args.get('lang')
    
    if lang:
        return lang
    return 'en'

babel.init_app(app, locale_selector=get_locale)


# Set up locale selection (You can modify this logic to use a dropdown or other methods)
 


# Set the environment variable for Google credentials
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "../mlbasket-f43c872cf2fb.json"

# Initialize Google Cloud Vertex AI
aiplatform.init(project="mlbasket", location="us-east1")

# Initialize the embedding model
embeddings = VertexAIEmbeddings(model_name="text-embedding-005")

# Load the FAISS index
vector_store = FAISS.load_local("faiss_index", embeddings=embeddings, allow_dangerous_deserialization=True)

# Initialize the Google Gemini language model
chat_model = ChatVertexAI(model_name="gemini-1.5-flash-001")

# Create a conversational chain
qa_chain = ConversationalRetrievalChain.from_llm(
    chat_model, retriever=vector_store.as_retriever()
)

# Initialize the Google Translate client
translate_client = translate.Client()

# Global variable to store the language being spoken (can be 'english', 'spanish', 'japanese')
language_spoken = 'english'  # Default to Spanish, can be dynamically changed


# Initialize BigQuery Client
client = bigquery.Client()




# Function to translate text using Google Translate API
def translate_text(text, target_language="en"):
    """Translate text to the target language."""
    translation = translate_client.translate(text, target_language=target_language)
    return translation['translatedText']

# Initialize chat history (per session, if needed)
chat_history = []

# Route for chatbot interaction
@app.route('/chat_with_bot', methods=['GET'])
def chat_with_bot():
    # Get player_id and question from the query parameters
    player_name = request.args.get('player_name')
    question = request.args.get('question')
    question = question + ' ' +player_name
    
    # Translate question if the language is Spanish or Japanese
    if language_spoken == 'spanish':
        question = translate_text(question, target_language="en")
        response_language = "spanish"
    elif language_spoken == 'japanese':
        question = translate_text(question, target_language="en")
        response_language = "japanese"
    else:
        response_language = "english"  # English, no translation

    # Format chat history for the chain
    chat_history_for_chain = []
    for i in range(0, len(chat_history), 2):
        try:
            human = chat_history[i]
            ai = chat_history[i + 1]
            chat_history_for_chain.append((human['content'], ai['content']))
        except IndexError:
            pass

    # Get response from the chain
    response = qa_chain.invoke({"question": question, "chat_history": chat_history_for_chain})

    # Translate the response if necessary
    if response_language == "spanish":
        response_text = translate_text(response['answer'], target_language="es")
    elif response_language == "japanese":
        response_text = translate_text(response['answer'], target_language="ja")
    else:
        response_text = response['answer']  # No translation needed for English

    # Update chat history
    chat_history.append({"role": "user", "content": question})
    chat_history.append({"role": "assistant", "content": response_text})

    # Return the chatbot's response as JSON
    return jsonify({"answer": response_text})


def get_player_details(player_id):
    try:
        # Fetch player data from MLB API
        player_url = f"https://statsapi.mlb.com/api/v1/people/{player_id}"
        response = requests.get(player_url)
        data = response.json()

        # Extract player information
        player = data['people'][0]
        return {
            "id": player_id,
            "name": player.get("fullName", "Unknown Player"),
            "team": player.get("currentTeam", {}).get("name", "Unknown Team"),
            "image_url": f"https://securea.mlb.com/mlb/images/players/head_shot/{player_id}.jpg"
        }
    except Exception as e:
        print(f"Error fetching data for Player {player_id}: {e}")
        return None

# Define a function to fetch data from BigQuery
def fetch_bigquery_results():
    query = """
	SELECT DISTINCT 
    	play.matchup.batter.id AS batter_id, 
    	play.matchup.batter.fullName AS batter_name, 
    	play.matchup.pitcher.id AS pitcher_id, 
	play.matchup.pitcher.fullName AS pitcher_name, 
	FROM `mlbasket.mlb.testall`, 
	UNNEST(liveData.plays.allPlays) AS play;
    """
    



    
    try:
        query_job = client.query(query)  # Run query
        results = [dict(row) for row in query_job]  # Convert results to list of dictionaries
        return results
    except Exception as e:
        return str(e)
        
@app.route('/load_players', methods=['GET'])
def load_players():
    data = fetch_bigquery_results()  # Run query when page loads
    BATTER_IDS = [item['batter_id'] for item in data]
    PITCHER_IDS = [item['pitcher_id'] for item in data]
    
    try:
        offset = int(request.args.get('offset', 0))  # Get the current batch offset
        limit = 10  # Number of players per batch

        # Combine both BATTER_IDS and PITCHER_IDS
        combined_ids = BATTER_IDS + PITCHER_IDS  # Concatenate both lists

        print(f"Fetching players from offset {offset}")  # Debugging

        # Get the next batch of player IDs (combined list of batters and pitchers)
        batch_ids = combined_ids[offset:offset + limit]

        # Fetch details for each player (either batter or pitcher)
        players = [get_player_details(player_id) for player_id in batch_ids]
        players = [p for p in players if p]  # Remove any failed fetches

        if not players:
            print("No more players to return!")  # Debugging

        return render_template('players.html', players=players)

    except Exception as e:
        print(f"Error in load_players: {e}")  # Debugging
        return str(e)



#@app.route('/')
#def index():
#    data = fetch_bigquery_results()  # Run query when page loads
#
#    BATTER_IDS = [item['batter_id'] for item in data]
#    pitcher_ids = [item['pitcher_id'] for item in data]
#    #return render_template('index.html', results=data)
#    players = [get_player_details(player_id) for player_id in BATTER_IDS]
#    players = [p for p in players if p]  # Remove any failed fetches
#    return render_template('index.html', players=players)


# Home Page

def fetch_play_events(player_id):
    query = f'''
    SELECT playEvent.playId, playEvent.details.description
    FROM `mlbasket.mlb.testall`, 
    UNNEST(liveData.plays.allPlays) AS play, 
    UNNEST(play.playEvents) AS playEvent
    WHERE play.matchup.batter.id = {player_id} 
    OR play.matchup.pitcher.id = {player_id}
    '''
    try:
        query_job = client.query(query)  # Run query
        results = [dict(row) for row in query_job]  # Convert results to list of dictionaries
        return results
    except Exception as e:
        return str(e)

@app.route('/get_play_events', methods=['GET'])
def get_play_events():
    player_id = request.args.get('player_id')
    if not player_id:
        return jsonify({"error": "Player ID is required"}), 400
    results = fetch_play_events(player_id)
    return jsonify(results)

@app.route('/get_video_url', methods=['GET'])
def get_video_url():
    play_id = request.args.get('play_id')
    if not play_id:
        return jsonify({"error": "Play ID is required"}), 400
    
    try:
        # Simulating video URL generation based on playId
        video_url = f"https://www.mlb.com/video/search?q=playid={play_id}"
        
        # Here, you might have logic to query a database or dataset to fetch the actual video URL
        # For example:
        # video_url = query_video_url_from_db(play_id)
        
        return jsonify({"video_url": video_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500




@app.route('/')
def index():
    current_language = get_locale()

    if  current_language == 'es':
        language_spoken = 'spanish'
    elif current_language == 'ja':
        language_spoken = 'japanese'
    return render_template('index.html')

    
if __name__ == '__main__':
    app.run(debug=True)    
