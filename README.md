# SwaggerToPy
This repository is the application files for a html frontend application that allows swagger descriptor files to be digested into a python class. This will facilitate software developers using APIs.

This repository contains a nodeJS setup to utilize the HTML interface that is powered by pyscript. To utlize the python script itself acquire the script called swaggertopy_external.py in the html\py folder. 

It has only two dependencies. 

-json
-re

Once the dependencies are installed add

import swaggertopy_external as swtpy

and execute it with 

output = swtpy.myEval(JSON)
output = output.genClass

Where JSON is the JSON input from a swagger file. The output of the initializer will put all plain text python code into 'genClass' which is where it can be retrieved. 


# License

This is released under a standard MIT license
