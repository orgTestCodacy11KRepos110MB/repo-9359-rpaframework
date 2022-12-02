import asyncio
import atexit
from dataclasses import dataclass
from datetime import date, datetime
import glob
import logging
import os
from pathlib import Path
import platform
import subprocess
import time
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple, Union

import flet
from flet import (
    Checkbox,
    Column,
    Control,
    Dropdown,
    ElevatedButton,
    FilePicker,
    FilePickerResultEvent,
    Image,
    Markdown,
    Page,
    Radio,
    RadioGroup,
    Text,
    TextField,
    app,
    colors,
    icons,
    ScrollMode
)
from flet.control_event import ControlEvent
from flet.dropdown import Option
from .date_picker import DatePicker

from robot.api.deco import keyword, library
from robot.libraries.BuiltIn import BuiltIn, RobotNotRunningError

from .dialog_types import Elements, Icon, Options, Result, Size
from .utils import int_or_auto, is_input, optional_int, optional_str, to_options

# TODO: delete, just a placeholder until we change all the dialog keywords
class Dialog:
    pass


class FletEvent:
    target: str
    name: str
    data: str
    control: Control
    page: Page


@library(scope="GLOBAL", doc_format="REST", auto_keywords=False)
class AssistantUI:
    """The `Dialogs` library provides a way to display information to a user
    and request input while a robot is running. It allows building processes
    that require human interaction.

    Some examples of use-cases could be the following:

    - Displaying generated files after an execution is finished
    - Displaying dynamic and user-friendly error messages
    - Requesting passwords or other personal information
    - Automating based on files created by the user

    **Workflow**

    The library is used to create dialogs, i.e. windows, that can be composed
    on-the-fly based on the current state of the execution.

    The content of the dialog is defined by calling relevant keywords
    such as ``Add text`` or ``Add file input``. When the dialog is opened
    the content is generated based on the previous keywords.

    Depending on the way the dialog is started, the execution will either
    block or continue while the dialog is open. During this time the user
    can freely edit any possible input fields or handle other tasks.

    After the user has successfully submitted the dialog, any possible
    entered input will be returned as a result. The user also has the option
    to abort by closing the dialog window forcefully.

    **Results**

    Each input field has a required ``name`` argument that controls what
    the value will be called in the result object. Each input name should be
    unique, and must not be called ``submit`` as that is reserved for the submit
    button value.

    A result object is a Robot Framework DotDict, where each key
    is the name of the input field and the value is what the user entered.
    The data type of each field depends on the input. For instance,
    a text input will have a string, a checkbox will have a boolean, and
    a file input will have a list of paths.

    If the user closed the window before submitting or there was an internal
    error, the library will raise an exception and the result values will
    not be available.

    **Examples**

    .. code-block:: robotframework

        Success dialog
            Add icon      Success
            Add heading   Your orders have been processed
            Add files     *.txt
            Run dialog    title=Success

        Failure dialog
            Add icon      Failure
            Add heading   There was an error
            Add text      The assistant failed to login to the Enterprise portal
            Add link      https://robocorp.com/docs    label=Troubleshooting guide
            Run dialog    title=Failure

        Large dialog
            Add heading    A real chonker   size=large
            Add image      fat-cat.jpeg
            Run dialog     title=Large    height=1024    width=1024

        Confirmation dialog
            Add icon      Warning
            Add heading   Delete user ${username}?
            Add submit buttons    buttons=No,Yes    default=Yes
            ${result}=    Run dialog
            IF   $result.submit == "Yes"
                Delete user    ${username}
            END

        Input form dialog
            Add heading       Send feedback
            Add text input    email    label=E-mail address
            Add text input    message
            ...    label=Feedback
            ...    placeholder=Enter feedback here
            ...    rows=5
            ${result}=    Run dialog
            Send feedback message    ${result.email}  ${result.message}

        Dialog as progress indicator
            Add heading    Please wait while I open a browser
            ${dialog}=     Show dialog    title=Please wait    on_top=${TRUE}
            Open available browser    https://robocorp.com
            Close dialog   ${dialog}
    """

    @property
    def current_elements(self):
        return self.elements[self._pagination]

    @property
    def current_invisible_elements(self):
        return self.invisible_elements[self._pagination]

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.elements: List[List[Control]] = [[]]
        self.invisible_elements: List[List[Control]] = [[]]
        self.results: Result = {}
        self._pagination = 0
        self.page: Optional[Page] = None
        self._conn = self._preload_flet()

        try:
            # Prevent logging from keywords that return results
            keywords = [
                "Run dialog",
                "Wait dialog",
                "Wait all dialogs",
            ]
            BuiltIn().import_library(
                "RPA.core.logger.RobotLogListener", "WITH NAME", "RPA.RobotLogListener"
            )
            listener = BuiltIn().get_library_instance("RPA.RobotLogListener")
            listener.register_protected_keywords(keywords)
        except RobotNotRunningError:
            pass

    """ TODO: delete, old implementation code
    def add_element(self, element: Dict[str, Any]) -> None:
        if is_input(element):
            name = element["name"]
            names = [
                el["name"] for el in self.elements if el["type"].startswith("input-")
            ]

            if name in names:
                raise ValueError(f"Input with name '{name}' already exists")

            if name == "submit":
                raise ValueError("Input name 'submit' is not allowed")

        self.elements.append(element)
    """

    def _preload_flet(self):
        return flet.flet._connect_internal(
            page_name="",
            host=None,
            port=0,
            is_app=True,
            permissions=None,
            assets_dir=None,
            upload_dir=None,
            web_renderer="canvaskit",
            route_url_strategy="hash",
        )

    def _show_flet(self, target):
        def on_session_created(conn, session_data):
            page = Page(conn, session_data.sessionID)
            conn.sessions[session_data.sessionID] = page
            try:
                assert target is not None
                target(page)
            except Exception as e:
                page.error(f"There was an error while rendering the page: {e}")

        self._conn.on_session_created = on_session_created
        fvp = flet.flet._open_flet_view(self._conn.page_url, False)
        try:
            fvp.wait()
        except Exception:
            pass

    def _make_flet_event_handler(self, name: str):
        def change_listener(e: FletEvent):
            self.results[name] = e.data
            e.page.update()

        return change_listener

    def add_element(self, element: flet.Control, name: Optional[str] = None):
        # TODO: validate that element "name" is unique
        self.elements[-1].append(element)
        if name is not None:
            # TODO: might be necessary to check that it doesn't already have change handler
            element.on_change = self._make_flet_event_handler(name)
            # element._add_event_handler("change", self._make_flet_event_handler(name))

    def add_invisible_element(self, element: flet.Control, name: Optional[str] = None):
        self.invisible_elements[-1].append(element)
        if name is not None:
            element.on_change = self._make_flet_event_handler(name)

    """
    def _collect_results(self) -> Result:
        result: Dict[str, Any] = {}
        for key, value in self.input_elements.items():
            result[key] = value.data
        return result
    """

    @keyword("Add Submit")
    def add_submit(self) -> None:
        def close(e):
            self.page.window_destroy()
        self.add_element(ElevatedButton("Submit", on_click=close))

    @keyword("Clear elements")
    def clear_elements(self) -> None:
        """Remove all previously defined elements and start from a clean state

        By default this is done automatically when a dialog is created.

        Example:

        .. code-block:: robotframework

            Add heading     Please input user information
            FOR    ${user}   IN    @{users}
                Run dialog    clear=False
                Process page
            END
            Clear elements
        """
        if self.page:
            self.page.controls.clear()
            self.page.overlay.clear()
            self.page.update()
        self.elements[self._pagination] = []
        self.invisible_elements[self._pagination] = []
        return

    @keyword("Add heading")
    def add_heading(
        self,
        heading: str,
        size: Size = Size.Medium,
    ) -> None:
        """Add a centered heading text element

        :param heading: The text content for the heading
        :param size:    The size of the heading

        Supported ``size`` values are Small, Medium, and Large. By default uses
        the value Medium.

        Example:

        .. code-block:: robotframework

            Add heading     User information  size=Large
            Add heading     Location          size=Small
            Add text input  address           label=User address
            Run dialog
        """
        if not isinstance(size, Size):
            size = Size(size)

        if size == Size.Small:
            self.add_element(element=Text(heading, style="headlineSmall"))
        elif size == Size.Medium:
            self.add_element(element=Text(heading, style="headlineMedium"))
        elif size == Size.Large:
            self.add_element(element=Text(heading, style="headlineLarge"))

    @keyword("Add text")
    def add_text(
        self,
        text: str,
        size: Size = Size.Medium,
    ) -> None:
        """Add a text paragraph element, for larger bodies of text

        :param text: The text content for the paragraph
        :param size: The size of the text

        Supported ``size`` values are Small, Medium, and Large. By default uses
        the value Medium.

        Example:

        .. code-block:: robotframework

            Add heading   An error occurred
            Add text      There was an error while requesting user information
            Add text      ${error}   size=Small
            Run dialog
        """
        if not isinstance(size, Size):
            size = Size(size)

        if size == Size.Small:
            self.add_element(element=Text(text, style="bodySmall"))
        elif size == Size.Medium:
            self.add_element(element=Text(text, style="bodyMedium"))
        elif size == Size.Large:
            self.add_element(element=Text(text, style="bodyLarge"))

    @keyword("Add link")
    def add_link(
        self,
        url: str,
        label: Optional[str] = None,
    ) -> None:
        """Add an external URL link element

        :param url:   The URL for the link
        :param label: A custom label text for the link

        Adds a clickable link element, which opens the user's default
        browser to the given ``url``. Optionally a ``label`` can be given
        which is shown as the link text, instead of the raw URL.

        Example:

        .. code-block:: robotframework

            Add heading    An error occurred
            Add text       See link for documentation
            Add link       https://robocorp.com/docs    label=Troubleshooting
            Run dialog
        """
        if not label:
            label = url
        self.add_element(Markdown(f"[{label}]({url})"))

    @keyword("Add image")
    def add_image(
        self,
        url_or_path: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> None:
        """Add an image element, from a local file or remote URL

        :param url_or_path: The location of the image
        :param width:       The static width of the image, in pixels
        :param height:      The static height of the image, in pixels

        Adds an inline image to the dialog, which can either
        point to a local file path on the executing machine or to
        a remote URL.

        By default the image is resized to fit the width of the dialog
        window, but the width and/or height can be explicitly defined
        to a custom value. If only one of the dimensions is given,
        the other is automatically changed to maintain the correct aspect ratio.

        Example:

        .. code-block:: robotframework

            Add image      company-logo.png
            Add heading    To start, please press the Continue button   size=Small
            Add submit buttons    Continue
            Run dialog
        """
        # TODO: confirm the url_or_path works with local paths with flet
        # FIXME: the image goes to a bit random location
        self.add_element(Image(src=url_or_path, width=width, height=height))

    @keyword("Add file")
    def add_file(
        self,
        path: str,
        label: Optional[str] = None,
    ) -> None:
        """Add a file element, which links to a local file

        :param path:  The path to the file
        :param label: A custom label text for the file

        Adds a button which opens a local file with the corresponding
        default application. Can be used for instance to display generated
        files from the robot to the end-user.

        Optionally a custom ``label`` can be given for the button text.
        By default uses the filename of the linked file.

        Example:

        .. code-block:: robotframework

            ${path}=   Generate order files
            Add heading    Current orders
            Add file    ${path}    label=Current
            Run dialog
        """
        resolved = Path(path).resolve()
        self.logger.info("Adding file: %s", resolved)

        if not resolved.exists():
            self.logger.warning("File does not exist: %s", resolved)

        def open_file(e):
            if platform.system() == "Windows":
                os.startfile(resolved)  # type: ignore # pylint: disable=no-member
            elif platform.system() == "Darwin":
                subprocess.call(["open", resolved])
            else:
                subprocess.call(["xdg-open", resolved])

        self.add_element(
            element=ElevatedButton(
                text=(label or str(resolved)), icon=icons.FILE_OPEN, on_click=open_file
            )
        )

    @keyword("Add files")
    def add_files(
        self,
        pattern: str,
    ) -> None:
        """Add multiple file elements according to the given file pattern

        :param pattern: File matching pattern

        See the keyword ``Add file`` for information about the inserted
        element itself.

        The keyword uses Unix-style glob patterns for finding matching files,
        and the supported pattern expressions are as follow:

        ========== ================================================
        Pattern    Meaning
        ========== ================================================
        ``*``      Match everything
        ``?``      Match any single character
        ``[seq]``  Match any character in seq
        ``[!seq]`` Match any character not in seq
        ``**``     Match all files, directories, and subdirectories
        ========== ================================================

        If a filename has any of these special characters, they
        can be escaped by wrapping them with square brackets.

        Example:

        .. code-block:: robotframework

            # Add all excel files
            Add files    *.xlsx

            # Add all log files in any subdirectory
            Add files    **/*.log

            # Add all PDFs between order0 and order9
            Add files    order[0-9].pdf
        """
        matches = glob.glob(pattern, recursive=True)
        for match in sorted(matches):
            self.add_file(match)

    @keyword("Add icon")
    def add_icon(self, variant: Icon, size: int = 48) -> None:
        """Add an icon element

        :param variant: The icon type
        :param size:    The size of the icon

        Adds an icon which can be used to indicate status
        or the type of dialog being presented.

        The currently supported icon types are:

        ======= ==========================
        Name    Description
        ======= ==========================
        Success A green check mark
        Warning An orange warning triangle
        Failure A red cross or X mark
        ======= ==========================

        The ``size`` of the icon can also be changed,
        to a given height/width of pixels.

        Example:

        .. code-block:: robotframework

            Add icon              Warning    size=64
            Add heading           Do you want to delete this order?
            Add submit buttons    buttons=No,Yes
            ${result}=    Run dialog
        """
        if not isinstance(variant, Icon):
            variant = Icon(variant)

        flet_icon_conversions: Dict[Icon, Tuple[str, str]] = {
            Icon.Success: (icons.CHECK, colors.GREEN_500),
            Icon.Warning: (icons.WARNING, colors.YELLOW_500),
            Icon.Failure: (icons.CLOSE, colors.RED_500),
        }
        flet_icon, color = flet_icon_conversions[variant]

        self.add_element(flet.Icon(name=flet_icon, color=color, size=size))

    @keyword("Add text input", tags=["input"])
    def add_text_input(
        self,
        name: str,
        label: Optional[str] = None,
        placeholder: Optional[str] = None,
        rows: Optional[int] = None,
    ) -> None:
        """Add a text input element

        :param name:        Name of result field
        :param label:       Label for field
        :param placeholder: Placeholder text in input field
        :param rows:        Number of input rows

        Adds a text field that can be filled by the user. The entered
        content will be available in the ``name`` field of the result.

        For customizing the look of the input, the ``label`` text can be given
        to add a descriptive label and the ``placholder`` text can be given
        to act as an example of the input value.

        If the ``rows`` argument is given as a number, the input is converted
        into a larger text area input with the given amount of rows by default.

        Example:

        .. code-block:: robotframework

            Add heading    Send feedback
            Add text input    email    label=E-mail address
            Add text input    message
            ...    label=Feedback
            ...    placeholder=Enter feedback here
            ...    rows=5
            ${result}=    Run dialog
            Send feedback message    ${result.email}  ${result.message}
        """
        # TODO: Do this in a cleaner way. Workaround because we use on_change
        # handlers to record values, so default value otherwise will be missed
        self.results[name] = placeholder

        self.add_element(name=name, element=TextField(label=label, value=placeholder))

    @keyword("Add password input", tags=["input"])
    def add_password_input(
        self,
        name: str,
        label: Optional[str] = None,
        placeholder: Optional[str] = None,
    ) -> None:
        """Add a password input element

        :param name:        Name of result field
        :param label:       Label for field
        :param placeholder: Placeholder text in input field

        Adds a text field that hides the user's input. The entered
        content will be available in the ``name`` field of the result.

        For customizing the look of the input, the ``label`` text can be given
        to add a descriptive label and the ``placholder`` text can be given
        to act as an example of the input value.

        Example:

        .. code-block:: robotframework

            Add heading    Change password
            Add text input        username    label=Current username
            Add password input    password    label=New password
            ${result}=    Run dialog
            Change user password    ${result.username}  ${result.password}
        """
        self.add_element(
            name=name, element=TextField(label=label, value=placeholder, password=True)
        )

    @keyword("Add hidden input", tags=["input"])
    def add_hidden_input(
        self,
        name: str,
        value: str,
    ) -> None:
        """Add a hidden input element

        :param name:  Name of result feild
        :param value: Value for input

        Adds a special hidden result field that is not visible
        to the user and always contains the given static value.

        Can be used to keep user input together with already known
        values such as user IDs, or to ensure that dialogs with differing
        elements all have the same fields in results.

        Example:

        .. code-block:: robotframework

            Add hidden input   user_id   ${USER_ID}
            Add text input     username
            ${result}=         Run dialog
            Enter user information    ${result.user_id}    ${result.username}
        """
        # FIXME: confirm that this works as expected with multi-page forms
        self.results[name] = value

    # SPLIT
    @keyword("Add file input", tags=["input"])
    def add_file_input(
        self,
        name: str,
        label: Optional[str] = None,
        source: Optional[str] = None,
        destination: Optional[str] = None,
        file_type: Optional[str] = None,
        multiple: bool = False,
    ) -> None:
        """Add a file input element

        :param name:        Name of result field
        :param label:       Label for input field
        :param source:      Default source directory
        :param destination: Target directory for selected files
        :param file_type:   Accepted file types
        :param multiple:    Allow selecting multiple files

        Adds a native file selection dialog for inputting one or more files.
        The list of selected files will be available in the ``name`` field
        of the result.

        By default opens up in the user's home directory, but it can be
        set to a custom path with the ``source`` argument.

        If the ``destination`` argument is not set, it returns the original
        paths to the selected files. If the ``destination`` directory
        is set, the files are copied there first and the new paths are
        returned.

        The argument ``file_type`` restricts the possible file extensions
        that the user can select. The format of the argument is as follows:
        ``Description text (*.ext1;*.ext2;...)``. For instance, an argument
        to limit options to Excel files could be: ``Excel files (*.xls;*.xlsx)``.

        To allow selecting more than one file, the ``multiple`` argument
        can be enabled.

        Example:

        .. code-block:: robotframework

            # This can be any one file
            Add file input    name=anyting

            # This can be multiple files
            Add file input    name=multiple  multiple=True

            # This opens the select dialog to a custom folder
            Add file input    name=src       source=C:\\Temp\\Output\\

            # This copies selected files to a custom folder
            Add file input    name=dest      destination=%{ROBOT_ROOT}

            # This restricts files to certain types
            Add file input    name=types     file_type=PDF files (*.pdf)

            # Every file input result is a list of paths
            ${result}=    Run dialog
            FOR    ${path}    IN    @{result.multiple}
                Log    Selected file: ${path}
            END
        """

        def on_pick_result(e: FilePickerResultEvent):
            if e.files:
                self.results[str(name)] = list(map(lambda f: f.path, e.files))

        file_picker = FilePicker(on_result=on_pick_result)
        self.add_invisible_element(file_picker)

        # TODO: use these inputs in some way
        element = {
            "source": optional_str(source),
            "destination": optional_str(destination),
            "file_type": optional_str(file_type),
        }

        self.add_element(
            ElevatedButton(
                label or "Choose files...",
                on_click=lambda _: file_picker.pick_files(
                    allow_multiple=bool(multiple)
                ),
            )
        )

    @keyword("Add drop-down", tags=["input"])
    def add_drop_down(
        self,
        name: str,
        options: Options,
        default: Optional[str] = None,
        label: Optional[str] = None,
    ) -> None:
        """Add a drop-down element

        :param name:    Name of result field
        :param options: List of drop-down options
        :param default: The default selection
        :param label:   Label for input field

        Creates a drop-down menu with the given ``options``. The selection
        the user makes will be available in the ``name`` field of the result.

        The ``default`` argument can be one of the defined options,
        and the dialog automatically selects that option for the input.

        A custom ``label`` text can also be added.

        Example:

        .. code-block:: robotframework

            Add heading     Select user type
            Add drop-down
            ...    name=user_type
            ...    options=Admin,Maintainer,Operator
            ...    default=Operator
            ...    label=User type
            ${result}=      Run dialog
            Log    User type should be: ${result.user_type}

        """
        options, default = to_options(options, default)

        options: List[Control] = list(map(Option, options))

        dropdown = Dropdown(options=options, value=default)

        self.add_element(Text(value=label))
        self.add_element(dropdown, name=str(name))

    @keyword("Add Date Input", tags=["input"])
    def add_date_input(
        self,
        name: str,
        default: Optional[Union[date, str]] = None,
        label: Optional[str] = None,
    ) -> None:
        """Add a date input element

        :param name:    Name of the result field
        :param default: The default set date
        :param label:   Label for the date input field

        Displays a date input widget. The selection the user makes will be available
        as a ``date`` object in the ``name`` field of the result.
        The ``default`` argument can be a pre-set date as object or string in
        "YYYY-MM-DD" format, otherwise the current date is used.

        Example:

        .. code-block:: robotframework

            Add heading       Enter your birthdate
            Add Date Input    birthdate    default=1993-04-26
            ${result} =       Run dialog
            Log To Console    User birthdate year should be: ${result.birthdate.year}
        """

        # TODO(cmin764): Be flexible on date formats. (provide it as parameter)
        # py_date_format = "%Y-%m-%d"
        # js_date_format = "yyyy-MM-dd"
        # default = default or datetime.utcnow().date()
        # if isinstance(default, date):  # recognizes both `date` and `datetime`
        #     default = default.strftime(py_date_format)
        # else:
        #     try:
        #         datetime.strptime(default, py_date_format)
        #     except Exception as exc:
        #         raise ValueError(
        #             f"Invalid default date with value {default!r}"
        #         ) from exc

        # element = {
        #     "type": "input-datepicker",
        #     "name": str(name),
        #     "_format": py_date_format,
        #     "format": js_date_format,
        #     "default": optional_str(default),
        #     "label": optional_str(label),
        # }
        # self.add_element(element)

        self.add_element(name=str(name), element=DatePicker())

    @keyword("Add radio buttons", tags=["input"])
    def add_radio_buttons(
        self,
        name: str,
        options: Options,
        default: Optional[str] = None,
        label: Optional[str] = None,
    ) -> None:
        """Add radio button elements

        :param name:    Name of result field
        :param options: List of drop-down options
        :param default: The default selection
        :param label:   Label for input field

        Creates a set of radio buttons with the given ``options``. The selection
        the user makes will be available in the ``name`` field of the result.

        The ``default`` argument can be one of the defined options,
        and the dialog automatically selects that option for the input.

        A custom ``label`` text can also be added.

        Example:

        .. code-block:: robotframework

            Add heading     Select user type
            Add radio buttons
            ...    name=user_type
            ...    options=Admin,Maintainer,Operator
            ...    default=Operator
            ...    label=User type
            ${result}=      Run dialog
            Log    User type should be: ${result.user_type}
        """
        options, default = to_options(options, default)
        radios: List[Control] = list(
            map(lambda option: Radio(value=option, label=option), options)
        )
        radio_group = RadioGroup(content=Column(radios), value=default)

        self.add_element(Text(value=label))
        self.add_element(radio_group, name=str(name))

    @keyword("Add checkbox", tags=["input"])
    def add_checkbox(
        self,
        name: str,
        label: str,
        default: bool = False,
    ) -> None:
        """Add a checkbox element

        :param name:    Name of result field
        :param label:   Label text for checkbox
        :param default: Default checked state

        Adds a checkbox that indicates a true or false value.
        The selection will be available in the ``name`` field of the result,
        and the ``label`` text will be shown next to the checkbox.

        The boolean ``default`` value will define the initial checked
        state of the element.

        Example:

        .. code-block:: robotframework

            Add heading     Enable features
            Add checkbox    name=vault        label=Enable vault       default=True
            Add checkbox    name=triggers     label=Enable triggers    default=False
            Add checkbox    name=assistants   label=Enable assistants  default=True
            ${result}=      Run dialog
            IF    $result.vault
                Enable vault
            END
        """
        self.add_element(
            name=str(name), element=Checkbox(label=str(label), value=bool(default))
        )

    @keyword
    def add_dialog_next_page_button(
        self,
        label: str,
    ) -> None:
        """Add a next page button

        :param label: The text displayed on the button

        The next page button will delimit the next elements of
        the dialog in a separate view, so that they will only be displayed after
        pressing the button, creating a wizard experience in the dialog.

        Example:

        .. code-block:: robotframework

            Add heading       Send feedback
            Add text input    email             label=E-mail address
            Add dialog next page button         label=next
            Add text input    name              label=Name
            Add dialog next page button         label=next
            Add checkbox      name=contact
            ...     label=Do you want us to contact you?
            ...     default=True
            Add dialog next page button         label=next
            Add text input    message
            ...    label=Feedback
            ...    placeholder=Enter feedback here
            ...    rows=5
            Add submit buttons  buttons=submit
            ${result}=    Run dialog
            Send feedback message    ${result.email}  ${result.message}
            Run dialog
        """

        def next_page(e):
            """Clear elements, increment pagination, make elements of next page visible"""
            self.clear_elements()
            self._pagination += 1
            for element in self.current_elements:
                self.page.add(element)
            self.page.update(*self.current_elements)

        self.add_element(ElevatedButton(text=str(label), on_click=next_page))
        # Add a new "page" of elements
        self.elements.append([])
        self.invisible_elements.append([])

    @keyword("Add submit buttons", tags=["input"])
    def add_submit_buttons(
        self,
        buttons: Options,
        default: Optional[str] = None,
    ) -> None:
        """Add custom submit buttons

        :param buttons: Submit button options
        :param default: The primary button

        The dialog automatically creates a button for closing itself.
        If there are no input fields, the button will say "Close".
        If there are one or more input fields, the button will say "Submit".

        If the submit button should have a custom label or there should be
        multiple options to choose from  when submitting, this keyword can
        be used to replace the automatically generated ones.

        The result field will always be called ``submit`` and will contain
        the pressed button text as a value.

        If one of the custom ``options`` should be the preferred option,
        the ``default`` argument controls which one is highlighted with
        an accent color.

        Example:

        .. code-block:: robotframework

            Add icon      Warning
            Add heading   Delete user ${username}?
            Add submit buttons    buttons=No,Yes    default=Yes
            ${result}=    Run dialog
            IF   $result.submit == "Yes"
                Delete user    ${username}
            END
        """
        buttons, _ = to_options(buttons, default)

        element = {
            "type": "submit",
            "buttons": buttons,
            "default": default,
        }

        self.add_element(element)

    @keyword("Run dialog", tags=["dialog"])
    def run_dialog(self, timeout: int = 180, **options: Any) -> Result:
        """Create a dialog from all the defined elements and block
        until the user has handled it.

        :param timeout: Time to wait for dialog to complete, in seconds
        :param options: Options for the dialog

        Returns a result object with all input values.
        This keyword is a shorthand for the following expression:

        .. code-block:: robotframework

            Run dialog
                [Arguments]  ${timeout}=180  &{options}
                ${dialog}=   Show dialog     &{options}
                ${result}=   Wait dialog     ${dialog}  timeout=${timeout}
                [Return]     ${result}

        For more information about possible options for opening the dialog,
        see the documentation for the keyword ``Show dialog``.

        Example:

        .. code-block:: robotframework

            Add heading     Please enter your username
            Add text input  name=username
            ${result}=      Run dialog
            Log    The username is: ${result.username}
        """

        # FIXME: support options

        def run(page: Page):
            # page.theme_mode = "light"
            for element in self.current_elements:
                page.add(element)
            for element in self.current_invisible_elements:
                page.overlay.append(element)
            page.scroll = ScrollMode.AUTO
            self.page = page
            page.update()

        self._show_flet(run)

        return self.results

    @keyword("Add Interactive Button", tags=["dialog"])
    def add_interactive_button(
        self, label: str, function: Union[Callable, str], *args, **kwargs
    ) -> None:
        """
        ``function`` should be a python function or a Robot keyword name, args and kwargs should be valid arguments for it.
        """

        # TODO: use logger.err and logger.debug
        def on_click(event: ControlEvent):
            if isinstance(function, Callable):
                try:
                    function(*args, **kwargs)
                except Exception as err:
                    print(f"on_click error with button labeled {label}")
                    print(err)
            else:
                try:
                    BuiltIn().run_keyword(function, *args, **kwargs)
                except Exception as err:
                    print(f"on_click error with button labeled {label}")
                    print(err)

        self.add_element(ElevatedButton(label, on_click=on_click))