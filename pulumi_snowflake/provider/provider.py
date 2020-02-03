from typing import List

from pulumi.dynamic import ResourceProvider, CreateResult, DiffResult

from pulumi_snowflake import ConnectionProvider
from pulumi_snowflake.validation import Validation
from pulumi_snowflake.random_id import RandomId
from .attribute import BaseAttribute


class Provider(ResourceProvider):
    """
    Generic base class for a Pulumi dynamic provider which manages Snowflake objects using a SQL connection.  Objects
    are described by passing in the SQL name of the object (e.g., "STORAGE INTEGRATION) and a list of attributes
    represented as `BaseAttribute` instances.  This class then automatically handles the create, delete and
    diff methods by generating and executing the appropriate SQL commands.

    This class can be instantiated directly, but there are a couple of methods which can be overridden to account
    for slight differences in the way objects are created (e.g., whether they are scoped to a schema or
    to the account).  These methods are `get_full_object_name` and `generate_outputs`.
    """

    def __init__(self,
                 connection_provider: ConnectionProvider,
                 sql_name: str,
                 attributes: List[BaseAttribute]):
        self.connection_provider = connection_provider
        self.sql_name = sql_name
        self.attributes = attributes
        Validation.validate_object_name(sql_name)


    def get_full_object_name(self, validated_name, inputs):
        """
        Returns the full object name which is used in statements such as CREATE and DELETE.  For globally-scoped
        objects this may just be the plain object name, but for schema-scoped objects the full name may be qualified
        by database and schema.
        :param validated_name: The object name.  This has already been validated to avoid SQL injection, and may have
        been autogenerated or derived from the inputs.
        :param inputs: The inputs to the create call which created this object.
        """
        return validated_name

    def generate_outputs(self, name, inputs, outs):
        """
        This method should be overridden by subclasses to modify the Pulumi outputs which are returned by the create
        method.  The `outs` parameter already contains an output for each of the attributes, so at least
        these values should included in the return value.
        """
        return outs

    def create(self, inputs):

        # Validate inputs
        self._check_required_attributes(inputs)
        validated_name = self._get_validated_autogenerated_name(inputs)
        attributes_with_values = list(filter(lambda a: inputs.get(a.name) is not None, self.attributes))

        # Perform SQL command to create object
        sql_statements = self._generate_sql_create_statement(attributes_with_values, validated_name, inputs)
        sql_bindings = self._generate_sql_create_bindings(attributes_with_values, inputs)
        self._execute_sql(sql_statements, sql_bindings)

        # Generate provisional outputs from attributes.  Provisional because the call to generate_outputs below allows
        # subclasses to modify them if necessary.
        provisional_outputs = {
            "name": validated_name,
            **self._generate_outputs_from_attributes(inputs)
        }
        
        return CreateResult(
            id_=validated_name,
            outs=self.generate_outputs(validated_name, inputs,provisional_outputs)
        )

    def diff(self, id, olds, news):
        """
        Simple implementation which forces a replacement if any fields have changed.
        """
        ignoreFields = ["name", "resource_name", "__provider"]
        oldFields = set(filter(lambda k: k not in ignoreFields, olds.keys()))
        newFields = set(filter(lambda k: k not in ignoreFields, news.keys()))
        fields = list(oldFields.union(newFields))

        changed_fields = []

        for field in fields:
            if olds.get(field) != news.get(field):
                changed_fields.append(field)

        if (news.get("name") is not None and olds.get("name") != news.get("name")):
            changed_fields.append("name")

        return DiffResult(
            changes=len(changed_fields) > 0,
            replaces=changed_fields,
            delete_before_replace=True
        )

    def delete(self, id, props):
        validated_name = Validation.validate_identifier(id)
        full_name = self.get_full_object_name(validated_name, props)
        self._execute_sql([f"DROP {self.sql_name} {full_name}"], None)


    def _check_required_attributes(self, inputs):
        """
        Raises an exception if a required attribute (including one of "name" or "resource_name") is not given
        """
        for attribute in self.attributes:
            if attribute.is_required() and inputs[attribute.name] is None:
                raise Exception(f"Required input attribute '{attribute.name}' is not present")

        if inputs.get("name") is None and inputs.get("resource_name") is None:
            raise Exception("At least one of 'name' or 'resource_name' must be provided")

    def _get_validated_autogenerated_name(self, inputs):
        """
        If an object name is not provided, autogenerates one from the resource name, and validates the name.
        """
        name = inputs.get("name")

        if name is None:
            name = f'{inputs["resource_name"]}_{RandomId.generate(7)}'

        return Validation.validate_identifier(name)

    def _generate_outputs_from_attributes(self, inputs):
        """
        Creates an outputs dictionary which has the value of every attribute.
        """
        outputs = {a.name: inputs.get(a.name) for a in self.attributes}
        return outputs

    def _generate_sql_create_statement(self, attributesWithValues, validated_name, inputs):
        """
        Generates the SQL statement which creates the object
        """
        
        qualified_name = self.get_full_object_name(validated_name, inputs)

        statements = [
            f"CREATE {self.sql_name} {qualified_name}",
            *list(map(lambda a: a.generate_sql(inputs.get(a.name)), attributesWithValues))
        ]

        return statements

    def _generate_sql_create_bindings(self, attributesWithValues, inputs):
        """
        Generates the list of binding values for all attributes
        """
        bindingTuplesList = list(map(lambda a: a.generate_bindings(inputs.get(a.name)), attributesWithValues))
        bindingTuplesList = filter(lambda t: t is not None, bindingTuplesList)
        bindings = [item for sublist in bindingTuplesList for item in sublist]
        return bindings

    def _execute_sql(self, statement, bindings):
        connection = self.connection_provider.get()
        cursor = connection.cursor()

        try:
            if bindings:
                cursor.execute('\n'.join(statement), (*bindings,))
            else:
                cursor.execute('\n'.join(statement))
        finally:
            cursor.close()

        connection.close()
