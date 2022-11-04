import RPA.AssistantUI
from RPA.AssistantUI.dialog_types import Icon

assistant = RPA.AssistantUI.AssistantUI()
assistant.add_heading("Heading test")
assistant.add_text("Test")
assistant.add_link("https://robocorp.com")
assistant.add_icon(Icon.Failure)
assistant.add_icon(Icon.Warning)
assistant.add_icon(Icon.Success)
assistant.add_text_input("txt_input", placeholder="placeholder")
assistant.add_password_input("pw_input")
assistant.add_checkbox("checkbox", "test_checkbox")
assistant.add_file_input("file")
assistant.add_hidden_input("Hidden", "value")
assistant.add_file(path="/Users/kerkko/Downloads/image.png", label="File")

assistant.add_radio_buttons(
    name="user_type_radio",
    options="Admin,Maintainer,Operator",
    default="Operator",
    label="User type",
)
assistant.add_drop_down(
    name="user_type_dropdown",
    options="Admin,Maintainer,Operator",
    default="Operator",
    label="User type",
)


assistant.add_dialog_next_page_button("Next page")

assistant.add_text_input("txt_input_2", placeholder="placeholder")
assistant.add_text("List python files")
assistant.add_files("**/*.py")
assistant.add_image(
    "https://robocorp.com/assets/home/global-purple.svg", width=256, height=256
)


# assistant.clear_elements()
# assistant.add_icon(Icon.Failure)

# not implemented yet
"""
assistant.add_date_input()
assistant.add_submit_buttons()

assistant.show_dialog()
assistant.wait_dialog()
assistant.wait_all_dialogs()
assistant.close_dialog()
assistant.close_all_dialogs()
assistant.wait_dialogs_as_completed()

"""

results = assistant.run_dialog()
print(results)
# FIXME: add a submit button to the dialog
