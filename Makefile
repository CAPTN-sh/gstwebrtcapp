PACKAGE := gstwebrtcapp
v := false

install:
ifeq ($(v), false)
	@poetry build -f wheel -o . > /dev/null
	@pip uninstall $(PACKAGE) -y --root-user-action=ignore > /dev/null
	@pip install *.whl --root-user-action=ignore > /dev/null
	@rm *.whl
	@echo "Successfully installed $(PACKAGE)"
else
	poetry build -f wheel -o .
	pip uninstall $(PACKAGE) -y --root-user-action=ignore
	pip install *.whl --root-user-action=ignore
	rm *.whl
	@echo "Successfully installed $(PACKAGE)"
endif

rehash:
	@poetry lock --no-update
	@poetry update
