# AI Financial Assistant

This is a desktop application developed with PySide6, functioning as an AI financial assistant. It leverages Alibaba Cloud's DashScope Application Center models to provide interactive chat capabilities, allowing users to get answers to their financial questions. The application supports API key configuration, model selection, chat history management, and a dark mode for enhanced user experience.

## Features

* **Interactive Chat**: Engage in conversations with an AI assistant for financial queries.
* **API Key and Model Configuration**: Easily set up your Alibaba Cloud DashScope API key and choose from various available models directly within the application's settings.
* **Chat History Management**:
    * Automatically saves chat sessions.
    * View and reload past conversations from a sidebar list.
    * Delete individual chat history files.
    * Start a new session by clearing the current chat.
* **Dark Mode Toggle**: Switch between light and dark themes for comfortable viewing in different environments.
* **User-Friendly Interface**: Built with PySide6 for a responsive and intuitive graphical user interface.
* **Logging**: Comprehensive logging for debugging and monitoring application activities and API requests.

## screencap



## Models Supported

The application supports the following models from DashScope Application Center:

* `deepseek-r1-distill-qwen-32b`
* `deepseek-r1`
* `qwen-plus`
* `qwen-max`

## Getting Started

### Prerequisites

* Python 3.x
* PySide6 library
* `dashscope` library
* An Alibaba Cloud account with access to DashScope and an API key.

### Installation

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/yourusername/ai-financial-assistant.git
    cd ai-financial-assistant
    ```

2.  **Install dependencies:**

    ```bash
    pip install PySide6 dashscope
    ```

### Running the Application

To start the AI Financial Assistant, run the `main.py` script:

```bash
python main.py
```

### Configuration

Upon first launch, or by clicking the "⚙ Settings" button, a settings dialog will appear:

1.  **API Key**: Enter your Alibaba Cloud DashScope API key here. This is crucial for the application to communicate with the AI models.
2.  **Select Model**: Choose your preferred AI model from the dropdown list.
3.  Click "Save" to apply your settings. The API key and selected model will be saved for future sessions.

## Usage

1.  **Start a Chat**: Type your financial questions or commands into the input box at the bottom.
2.  **Send Message**: Press `Ctrl+Enter` or click the "Send ✉️" button to send your message.
3.  **Reset Conversation**: Type `/reset` in the input box and send it to clear the current chat history and start a new session. This will also save the current conversation.
4.  **View History**: The left sidebar displays a list of your past chat sessions, ordered by date. Click on an item to load and view that conversation.
5.  **Delete History**: Each history item in the sidebar has a delete button (🗑️ or "删"). Click it to remove a specific chat history file.
6.  **Toggle Dark Mode**: Click the "🌙 Dark Mode" button to switch between dark and light themes.

## Project Structure

* `main.py`: The entry point of the application, responsible for setting up the QApplication and launching the main GUI window. It also configures basic logging.
* `gui.py`: Contains the `ChatGUI` class, which defines the main window, UI elements, and handles user interactions, chat display, settings, and history management.
* `controller.py`: Manages the interaction with the DashScope API. It includes the `Controller` class with a static method `process_api_request` for sending messages to the AI models and handling responses.
* `assets/`: Directory for static assets such as icons (`logo.ico`, `user.ico`, `robot.ico`, `delete.png`) and stylesheets (`dark_mode.qss`, `light_mode.qss`, `dark_mode_history.css`, `light_mode_history.css`).
* `history/`: Directory where chat history HTML files are stored.

## Logging

The application uses the `logging` module to record informational messages, warnings, and errors to the console. This is helpful for debugging and tracking the application's behavior.

## Future Enhancements

* Export chat history to various formats (e.g., PDF, TXT).
* Search functionality for chat history.
* More advanced settings for model parameters (e.g., temperature, top_p).
* Support for streaming responses from the API.

## Contributing

Feel free to fork the repository, open issues, and submit pull requests.
